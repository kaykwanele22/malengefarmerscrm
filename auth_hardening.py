"""Persistent account-security and authentication lifecycle controls.

This module layers durable account lockout, temporary-password rotation, session
revocation and per-user security history onto the existing CRM authentication
without weakening the existing Google Authenticator flow.
"""
import importlib
import os
import re
import sys
from datetime import timedelta

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash

_core = sys.modules.get("__main__")
if _core is None or not hasattr(_core, "db"):
    _core = importlib.import_module("app")

for _name in (
    "db", "User", "UserAccess", "AuditLog", "roles_required", "login_required",
    "current_user", "current_access", "add_audit_log", "utc_now",
    "client_ip_address", "two_factor_policy_enabled", "two_factor_is_required", "two_factor_session_complete",
):
    globals()[_name] = getattr(_core, _name)

bp = Blueprint("authsec", __name__)

ACCOUNT_LOCK_FAILURES = max(3, int(os.getenv("ACCOUNT_LOCK_FAILURES", "5")))
ACCOUNT_LOCK_MINUTES = max(1, int(os.getenv("ACCOUNT_LOCK_MINUTES", "15")))
PASSWORD_MIN_LENGTH = max(10, int(os.getenv("PASSWORD_MIN_LENGTH", "10")))
SESSION_IDLE_MINUTES = max(5, int(os.getenv("SESSION_IDLE_MINUTES", "30")))
SESSION_ABSOLUTE_HOURS = max(1, int(os.getenv("SESSION_ABSOLUTE_HOURS", "12")))
_SESSION_STARTED_KEY = "_security_session_started"
_SESSION_LAST_SEEN_KEY = "_security_session_last_seen"


class UserSecurity(db.Model):
    """Durable authentication state kept separately from profile/access records."""
    __tablename__ = "user_security"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True, index=True)
    last_login_at = db.Column(db.DateTime, nullable=True, index=True)
    last_login_ip = db.Column(db.String(64), nullable=True)
    last_login_user_agent = db.Column(db.String(255), nullable=True)
    password_changed_at = db.Column(db.DateTime, nullable=True)
    auth_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("security_record", uselist=False))


def _security(user_id, create=True):
    row = UserSecurity.query.filter_by(user_id=user_id).first()
    if row is None and create:
        row = UserSecurity(user_id=user_id)
        db.session.add(row)
        db.session.flush()
    return row


def security_state(user_id):
    """Safe display state for templates without mutating the database."""
    row = _security(user_id, create=False)
    now = utc_now()
    return {
        "must_change_password": bool(row.must_change_password) if row else False,
        "failed_login_count": int(row.failed_login_count or 0) if row else 0,
        "locked": bool(row and row.locked_until and row.locked_until > now),
        "locked_until": row.locked_until if row else None,
        "last_login_at": row.last_login_at if row else None,
        "last_login_ip": row.last_login_ip if row else None,
        "password_changed_at": row.password_changed_at if row else None,
        "auth_version": int(row.auth_version or 1) if row else 1,
    }


def password_strength_error(password, user=None):
    value = str(password or "")
    if len(value) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if not re.search(r"[A-Z]", value):
        return "Password must include an uppercase letter."
    if not re.search(r"[a-z]", value):
        return "Password must include a lowercase letter."
    if not re.search(r"\d", value):
        return "Password must include a number."
    if not re.search(r"[^A-Za-z0-9]", value):
        return "Password must include a symbol."
    if user and check_password_hash(user.password, value):
        return "Choose a new password that is different from the current password."
    return None


def _unlock_if_expired(security):
    if security.locked_until and security.locked_until <= utc_now():
        security.locked_until = None
        security.failed_login_count = 0
        return True
    return False


def _record_persistent_failure(user, security):
    security.failed_login_count = int(security.failed_login_count or 0) + 1
    if security.failed_login_count >= ACCOUNT_LOCK_FAILURES:
        security.locked_until = utc_now() + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
        add_audit_log(
            "ACCOUNT_LOCKED",
            "User",
            user.id,
            f"Account locked for {ACCOUNT_LOCK_MINUTES} minutes after repeated password failures.",
            cooperative_id=user.access_record.cooperative_id if user.access_record else None,
            user_id=user.id,
        )


def _clear_failures(security):
    security.failed_login_count = 0
    security.locked_until = None


def _mark_authenticated_login(user):
    security = _security(user.id)
    _clear_failures(security)
    security.last_login_at = utc_now()
    security.last_login_ip = client_ip_address()
    security.last_login_user_agent = (request.headers.get("User-Agent", "") or "")[:255] or None
    session["auth_version"] = int(security.auth_version or 1)
    session["_auth_login_recorded_for"] = user.id
    _establish_session_window(reset=True)
    db.session.commit()
    return security


def _target_user_id_from_path(prefix):
    match = re.match(rf"^{re.escape(prefix)}(\d+)$", request.path)
    return int(match.group(1)) if match else None


def _session_now():
    return int(utc_now().timestamp())


def _establish_session_window(reset=False):
    """Create or refresh the bounded authenticated-session window."""
    now = _session_now()
    if reset or not session.get(_SESSION_STARTED_KEY):
        session[_SESSION_STARTED_KEY] = now
    if reset or not session.get(_SESSION_LAST_SEEN_KEY):
        session[_SESSION_LAST_SEEN_KEY] = now
    return now


def _expire_authenticated_session(user, reason):
    cooperative_id = user.access_record.cooperative_id if user.access_record else None
    user_id = user.id
    session.clear()
    add_audit_log(
        "SESSION_EXPIRED",
        "User",
        user_id,
        f"Authenticated session ended after {reason}.",
        cooperative_id=cooperative_id,
        user_id=user_id,
    )
    db.session.commit()
    return redirect(url_for("login"))


def _enforce_session_window(user):
    """Expire idle or overlong authenticated sessions and refresh valid activity."""
    now = _session_now()
    try:
        started = int(session.get(_SESSION_STARTED_KEY, now))
        last_seen = int(session.get(_SESSION_LAST_SEEN_KEY, now))
    except (TypeError, ValueError):
        started = now
        last_seen = now

    session[_SESSION_STARTED_KEY] = started
    session[_SESSION_LAST_SEEN_KEY] = last_seen

    if now - started > SESSION_ABSOLUTE_HOURS * 60 * 60:
        return _expire_authenticated_session(user, "the maximum session lifetime")
    if now - last_seen > SESSION_IDLE_MINUTES * 60:
        return _expire_authenticated_session(user, "the inactivity timeout")

    session[_SESSION_LAST_SEEN_KEY] = now
    return None


def _password_preflight():
    """Apply one password standard to bootstrap, Admin and self-service changes."""
    endpoint = request.endpoint or ""
    if request.method != "POST":
        return None

    password = None
    compare_user = None
    if endpoint == "register":
        password = request.form.get("password", "")
    elif endpoint == "add_user":
        password = request.form.get("password", "")
    elif endpoint == "reset_user_password":
        password = request.form.get("new_password", "")
        target_id = _target_user_id_from_path("/users/reset-password/")
        compare_user = db.session.get(User, target_id) if target_id else None
    elif endpoint == "change_password":
        password = request.form.get("new_password", "")
        compare_user = current_user()
    elif endpoint == "authsec.change_required_password":
        password = request.form.get("new_password", "")
        compare_user = current_user()
    else:
        return None

    error = password_strength_error(password, compare_user)
    if error:
        return error, 400
    return None


def _auth_before_request():
    preflight = _password_preflight()
    if preflight:
        return preflight

    # Persistent per-account lockout supplements the existing IP/process throttle.
    if request.endpoint == "login" and request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user:
            security = _security(user.id)
            changed = _unlock_if_expired(security)
            if security.locked_until and security.locked_until > utc_now():
                add_audit_log(
                    "LOGIN_ACCOUNT_LOCKED", "User", user.id,
                    "Password login blocked while persistent account lock is active.",
                    cooperative_id=user.access_record.cooperative_id if user.access_record else None,
                    user_id=user.id,
                )
                db.session.commit()
                return "Too many failed login attempts. Please wait before trying again.", 429
            if not check_password_hash(user.password, password):
                _record_persistent_failure(user, security)
                db.session.commit()
            elif changed:
                db.session.commit()

    if not session.get("user_id"):
        return None

    user = db.session.get(User, session.get("user_id"))
    if not user:
        session.clear()
        return redirect(url_for("login"))

    security = _security(user.id)
    if security.id and security not in db.session.new:
        _unlock_if_expired(security)

    current_version = int(security.auth_version or 1)
    session_version = session.get("auth_version")
    if session_version is None:
        # Preserve legacy sessions created before this hardening was deployed.
        session["auth_version"] = current_version
    elif int(session_version) != current_version:
        session.clear()
        return redirect(url_for("login"))

    if (request.endpoint or "") != "static":
        timeout_response = _enforce_session_window(user)
        if timeout_response is not None:
            return timeout_response

    # Flask saves the session after response hooks, so the login POST may not expose
    # its freshly-created session to this module's after_request callback. Record a
    # successful login exactly once on the first subsequent authenticated request.
    # Second-factor challenge endpoints are excluded so this never treats an
    # unfinished Google Authenticator challenge as a completed login.
    endpoint = request.endpoint or ""
    if (
        session.get("_auth_login_recorded_for") != user.id
        and endpoint not in {"two_factor_setup", "two_factor_verify"}
        and (not two_factor_is_required() or two_factor_session_complete())
    ):
        security = _mark_authenticated_login(user)

    exempt = {
        "home", "login", "logout", "health", "static",
        "two_factor_setup", "two_factor_verify",
        "authsec.change_required_password",
    }
    if security.must_change_password and (request.endpoint or "") not in exempt:
        # Existing 2FA remains the first gate. Only force rotation after a complete
        # second factor (or while the global 2FA policy is intentionally paused).
        if not two_factor_is_required() or two_factor_session_complete():
            return redirect(url_for("authsec.change_required_password"))
    return None


def _auth_after_request(response):
    endpoint = request.endpoint or ""

    # Final successful authentication establishes login metadata and session version.
    if request.method == "POST" and session.get("user_id"):
        finalized = False
        if endpoint == "login" and response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "") or ""
            challenge_paths = (url_for("two_factor_setup"), url_for("two_factor_verify"))
            # A login redirect is final unless the existing login flow is explicitly
            # sending the user to a second-factor challenge. This preserves mandatory
            # 2FA while also supporting environments where 2FA enforcement is paused.
            finalized = all(path not in location for path in challenge_paths)
        elif endpoint == "two_factor_verify" and two_factor_session_complete():
            finalized = response.status_code in {301, 302, 303, 307, 308}
        elif endpoint == "two_factor_setup" and two_factor_session_complete():
            finalized = response.status_code < 400

        if finalized:
            user = db.session.get(User, session.get("user_id"))
            if user:
                security = _mark_authenticated_login(user)
                if (
                    security.must_change_password
                    and endpoint != "two_factor_setup"
                    and response.status_code in {301, 302, 303, 307, 308}
                ):
                    response.headers["Location"] = url_for("authsec.change_required_password")

    # Successful Admin/user lifecycle actions update durable security state.
    if request.method == "POST" and response.status_code in {301, 302, 303, 307, 308}:
        if endpoint == "add_user":
            email = request.form.get("email", "").strip().lower()
            user = User.query.filter_by(email=email).first()
            if user:
                security = _security(user.id)
                security.must_change_password = True
                security.password_changed_at = None
                db.session.commit()

        elif endpoint == "reset_user_password":
            target_id = _target_user_id_from_path("/users/reset-password/")
            if target_id:
                security = _security(target_id)
                security.must_change_password = True
                security.password_changed_at = None
                security.auth_version = int(security.auth_version or 1) + 1
                _clear_failures(security)
                db.session.commit()

        elif endpoint == "reset_user_two_factor":
            target_id = _target_user_id_from_path("/users/reset-2fa/")
            if target_id:
                security = _security(target_id)
                security.auth_version = int(security.auth_version or 1) + 1
                db.session.commit()

        elif endpoint == "update_user_access":
            target_id = _target_user_id_from_path("/users/access/")
            if target_id and request.form.get("status", "").strip() == "Inactive":
                security = _security(target_id)
                security.auth_version = int(security.auth_version or 1) + 1
                db.session.commit()

        elif endpoint == "change_password" and session.get("user_id"):
            security = _security(session["user_id"])
            security.must_change_password = False
            security.password_changed_at = utc_now()
            security.auth_version = int(security.auth_version or 1) + 1
            _clear_failures(security)
            session["auth_version"] = security.auth_version
            session["_csrf_token"] = os.urandom(24).hex()
            _establish_session_window(reset=True)
            db.session.commit()

    # Dynamic CRM responses can contain personal, governance or finance data.
    # Do not allow browsers or shared proxies to retain those pages after logout.
    if endpoint != "static":
        response.headers["Cache-Control"] = "no-store, private, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    # Modern cross-origin isolation headers complement the core CSP/frame policy.
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

    # Reverse proxies terminate TLS in production, so request.is_secure alone may
    # not reflect the original HTTPS request. Only trust X-Forwarded-Proto when
    # TRUST_PROXY_HEADERS is explicitly enabled.
    forwarded_proto = (request.headers.get("X-Forwarded-Proto", "") or "").split(",", 1)[0].strip().lower()
    trusted_https = bool(_core.app.config.get("TRUST_PROXY_HEADERS") and forwarded_proto == "https")
    if request.is_secure or trusted_https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    return response


@bp.route("/password/change-required", methods=["GET", "POST"])
@login_required
def change_required_password():
    user = current_user()
    access = current_access()
    security = _security(user.id)
    if not security.must_change_password:
        return redirect(url_for("dashboard"))

    if two_factor_is_required() and not two_factor_session_complete():
        if user.two_factor_enabled:
            return redirect(url_for("two_factor_verify"))
        return redirect(url_for("two_factor_setup"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not check_password_hash(user.password, current_password):
            return "Current temporary password is incorrect.", 400
        if new_password != confirm_password:
            return "New passwords do not match.", 400
        error = password_strength_error(new_password, user)
        if error:
            return error, 400

        user.password = generate_password_hash(new_password)
        security.must_change_password = False
        security.password_changed_at = utc_now()
        security.auth_version = int(security.auth_version or 1) + 1
        _clear_failures(security)
        session["auth_version"] = security.auth_version
        session["_csrf_token"] = os.urandom(24).hex()
        _establish_session_window(reset=True)
        add_audit_log(
            "PASSWORD_ROTATED_REQUIRED", "User", user.id,
            "Temporary/Admin-reset password replaced by the account holder.",
            cooperative_id=access.cooperative_id if access else None,
        )
        db.session.commit()
        return redirect(url_for("dashboard"))

    return render_template("auth/change_required_password.html", user=user, minimum_length=PASSWORD_MIN_LENGTH)


@bp.route("/users/<int:user_id>/security")
@roles_required("Admin")
def user_security_history(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    access = UserAccess.query.filter_by(user_id=user.id).first()
    security = _security(user.id)
    logs = AuditLog.query.filter(or_(
        AuditLog.user_id == user.id,
        (AuditLog.entity_type == "User") & (AuditLog.entity_id == user.id),
    )).order_by(AuditLog.created_at.desc()).limit(200).all()
    db.session.commit()
    return render_template(
        "auth/user_security.html",
        target_user=user,
        access=access,
        security=security,
        logs=logs,
        now=utc_now(),
    )


@bp.route("/users/<int:user_id>/unlock", methods=["POST"])
@roles_required("Admin")
def unlock_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    security = _security(user.id)
    was_locked = bool(security.locked_until or security.failed_login_count)
    _clear_failures(security)
    if was_locked:
        add_audit_log(
            "ACCOUNT_UNLOCKED", "User", user.id,
            "Admin cleared persistent failed-login lock state.",
            cooperative_id=user.access_record.cooperative_id if user.access_record else None,
        )
    db.session.commit()
    return redirect(url_for("authsec.user_security_history", user_id=user.id))


def register_auth_hardening(app):
    if "authsec" not in app.blueprints:
        app.register_blueprint(bp)
    if not app.extensions.get("auth_hardening_hooks_registered"):
        app.before_request(_auth_before_request)
        app.after_request(_auth_after_request)
        app.extensions["auth_hardening_hooks_registered"] = True
    app.jinja_env.globals["auth_security_state"] = security_state
