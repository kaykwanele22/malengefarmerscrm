from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Could not find patch anchor: {label}")
    return text.replace(old, new, 1)


def patch_auth_hardening():
    path = ROOT / "auth_hardening.py"
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'PASSWORD_MIN_LENGTH = max(10, int(os.getenv("PASSWORD_MIN_LENGTH", "10")))\n',
        'PASSWORD_MIN_LENGTH = max(10, int(os.getenv("PASSWORD_MIN_LENGTH", "10")))\n'
        'SESSION_IDLE_MINUTES = max(5, int(os.getenv("SESSION_IDLE_MINUTES", "30")))\n'
        'SESSION_ABSOLUTE_HOURS = max(1, int(os.getenv("SESSION_ABSOLUTE_HOURS", "12")))\n'
        '_SESSION_STARTED_KEY = "_security_session_started"\n'
        '_SESSION_LAST_SEEN_KEY = "_security_session_last_seen"\n',
        "session policy constants",
    )

    helper_anchor = '''def _target_user_id_from_path(prefix):\n    match = re.match(rf"^{re.escape(prefix)}(\\d+)$", request.path)\n    return int(match.group(1)) if match else None\n\n\n'''
    helper_block = '''def _target_user_id_from_path(prefix):\n    match = re.match(rf"^{re.escape(prefix)}(\\d+)$", request.path)\n    return int(match.group(1)) if match else None\n\n\ndef _session_now():\n    return int(utc_now().timestamp())\n\n\ndef _establish_session_window(reset=False):\n    """Create or refresh the bounded authenticated-session window."""\n    now = _session_now()\n    if reset or not session.get(_SESSION_STARTED_KEY):\n        session[_SESSION_STARTED_KEY] = now\n    if reset or not session.get(_SESSION_LAST_SEEN_KEY):\n        session[_SESSION_LAST_SEEN_KEY] = now\n    return now\n\n\ndef _expire_authenticated_session(user, reason):\n    cooperative_id = user.access_record.cooperative_id if user.access_record else None\n    user_id = user.id\n    session.clear()\n    add_audit_log(\n        "SESSION_EXPIRED",\n        "User",\n        user_id,\n        f"Authenticated session ended after {reason}.",\n        cooperative_id=cooperative_id,\n        user_id=user_id,\n    )\n    db.session.commit()\n    return redirect(url_for("login"))\n\n\ndef _enforce_session_window(user):\n    """Expire idle or overlong authenticated sessions and refresh valid activity."""\n    now = _session_now()\n    try:\n        started = int(session.get(_SESSION_STARTED_KEY, now))\n        last_seen = int(session.get(_SESSION_LAST_SEEN_KEY, now))\n    except (TypeError, ValueError):\n        started = now\n        last_seen = now\n\n    session[_SESSION_STARTED_KEY] = started\n    session[_SESSION_LAST_SEEN_KEY] = last_seen\n\n    if now - started > SESSION_ABSOLUTE_HOURS * 60 * 60:\n        return _expire_authenticated_session(user, "the maximum session lifetime")\n    if now - last_seen > SESSION_IDLE_MINUTES * 60:\n        return _expire_authenticated_session(user, "the inactivity timeout")\n\n    session[_SESSION_LAST_SEEN_KEY] = now\n    return None\n\n\n'''
    text = replace_once(text, helper_anchor, helper_block, "session helpers")

    text = replace_once(
        text,
        '    session["auth_version"] = int(security.auth_version or 1)\n    session["_auth_login_recorded_for"] = user.id\n',
        '    session["auth_version"] = int(security.auth_version or 1)\n    session["_auth_login_recorded_for"] = user.id\n    _establish_session_window(reset=True)\n',
        "successful login session establishment",
    )

    version_anchor = '''    elif int(session_version) != current_version:\n        session.clear()\n        return redirect(url_for("login"))\n\n    # Flask saves the session after response hooks, so the login POST may not expose\n'''
    version_replacement = '''    elif int(session_version) != current_version:\n        session.clear()\n        return redirect(url_for("login"))\n\n    if (request.endpoint or "") != "static":\n        timeout_response = _enforce_session_window(user)\n        if timeout_response is not None:\n            return timeout_response\n\n    # Flask saves the session after response hooks, so the login POST may not expose\n'''
    text = replace_once(text, version_anchor, version_replacement, "session timeout enforcement")

    text = replace_once(
        text,
        '            session["auth_version"] = security.auth_version\n            session["_csrf_token"] = os.urandom(24).hex()\n            db.session.commit()\n',
        '            session["auth_version"] = security.auth_version\n            session["_csrf_token"] = os.urandom(24).hex()\n            _establish_session_window(reset=True)\n            db.session.commit()\n',
        "self-service password rotation session reset",
    )

    text = replace_once(
        text,
        '        session["auth_version"] = security.auth_version\n        session["_csrf_token"] = os.urandom(24).hex()\n        add_audit_log(\n',
        '        session["auth_version"] = security.auth_version\n        session["_csrf_token"] = os.urandom(24).hex()\n        _establish_session_window(reset=True)\n        add_audit_log(\n',
        "required password rotation session reset",
    )

    after_anchor = '''    return response\n\n\n@bp.route("/password/change-required", methods=["GET", "POST"])\n'''
    after_replacement = '''    # Dynamic CRM responses can contain personal, governance or finance data.\n    # Do not allow browsers or shared proxies to retain those pages after logout.\n    if endpoint != "static":\n        response.headers["Cache-Control"] = "no-store, private, max-age=0"\n        response.headers["Pragma"] = "no-cache"\n        response.headers["Expires"] = "0"\n\n    # Modern cross-origin isolation headers complement the core CSP/frame policy.\n    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")\n    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")\n\n    # Reverse proxies terminate TLS in production, so request.is_secure alone may\n    # not reflect the original HTTPS request. Only trust X-Forwarded-Proto when\n    # TRUST_PROXY_HEADERS is explicitly enabled.\n    forwarded_proto = (request.headers.get("X-Forwarded-Proto", "") or "").split(",", 1)[0].strip().lower()\n    trusted_https = bool(_core.app.config.get("TRUST_PROXY_HEADERS") and forwarded_proto == "https")\n    if request.is_secure or trusted_https:\n        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")\n\n    return response\n\n\n@bp.route("/password/change-required", methods=["GET", "POST"])\n'''
    text = replace_once(text, after_anchor, after_replacement, "response hardening headers")

    path.write_text(text, encoding="utf-8")


def patch_auth_tests():
    path = ROOT / "auth_hardening_regression_tests.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''    def test_admin_security_history_is_admin_only(self):\n        self.login_session_as(self.treasurer_id, "Lifecycle Treasurer")\n        self.assertEqual(self.client.get(f"/users/{self.treasurer_id}/security").status_code, 403)\n\n        self.login_session_as(self.admin_id, "Lifecycle Admin")\n        response = self.client.get(f"/users/{self.treasurer_id}/security")\n        self.assertEqual(response.status_code, 200)\n        self.assertIn(b"Security &amp; Access Activity", response.data)\n        self.assertIn(b"Lifecycle Treasurer", response.data)\n\n\n'''
    replacement = anchor + '''    def test_authenticated_session_has_bounded_window_and_private_cache_headers(self):\n        self.login_session_as(self.treasurer_id, "Lifecycle Treasurer")\n        response = self.client.get("/dashboard", follow_redirects=False)\n        self.assertEqual(response.status_code, 200)\n        self.assertEqual(response.headers.get("Cache-Control"), "no-store, private, max-age=0")\n        self.assertEqual(response.headers.get("Pragma"), "no-cache")\n        self.assertEqual(response.headers.get("Cross-Origin-Opener-Policy"), "same-origin")\n        self.assertEqual(response.headers.get("Cross-Origin-Resource-Policy"), "same-origin")\n        with self.client.session_transaction() as sess:\n            self.assertTrue(sess.get(self.auth._SESSION_STARTED_KEY))\n            self.assertTrue(sess.get(self.auth._SESSION_LAST_SEEN_KEY))\n\n    def test_idle_session_timeout_revokes_login_and_is_audited(self):\n        self.login_session_as(self.treasurer_id, "Lifecycle Treasurer")\n        now = int(self.crm.utc_now().timestamp())\n        with self.client.session_transaction() as sess:\n            sess[self.auth._SESSION_STARTED_KEY] = now - (self.auth.SESSION_IDLE_MINUTES * 60 + 120)\n            sess[self.auth._SESSION_LAST_SEEN_KEY] = now - (self.auth.SESSION_IDLE_MINUTES * 60 + 1)\n\n        response = self.client.get("/dashboard", follow_redirects=False)\n        self.assertEqual(response.status_code, 302)\n        self.assertIn("/login", response.headers.get("Location", ""))\n        with self.client.session_transaction() as sess:\n            self.assertFalse(bool(sess.get("user_id")))\n        with self.crm.app.app_context():\n            log = self.crm.AuditLog.query.filter_by(\n                action="SESSION_EXPIRED", entity_id=self.treasurer_id\n            ).order_by(self.crm.AuditLog.id.desc()).first()\n            self.assertIsNotNone(log)\n            self.assertIn("inactivity timeout", log.details)\n\n    def test_absolute_session_lifetime_revokes_recently_active_session(self):\n        self.login_session_as(self.treasurer_id, "Lifecycle Treasurer")\n        now = int(self.crm.utc_now().timestamp())\n        with self.client.session_transaction() as sess:\n            sess[self.auth._SESSION_STARTED_KEY] = now - (self.auth.SESSION_ABSOLUTE_HOURS * 60 * 60 + 1)\n            sess[self.auth._SESSION_LAST_SEEN_KEY] = now - 1\n\n        response = self.client.get("/dashboard", follow_redirects=False)\n        self.assertEqual(response.status_code, 302)\n        self.assertIn("/login", response.headers.get("Location", ""))\n        with self.crm.app.app_context():\n            log = self.crm.AuditLog.query.filter_by(\n                action="SESSION_EXPIRED", entity_id=self.treasurer_id\n            ).order_by(self.crm.AuditLog.id.desc()).first()\n            self.assertIsNotNone(log)\n            self.assertIn("maximum session lifetime", log.details)\n\n    def test_trusted_https_proxy_sets_hsts(self):\n        previous = self.crm.app.config.get("TRUST_PROXY_HEADERS")\n        self.crm.app.config["TRUST_PROXY_HEADERS"] = True\n        try:\n            response = self.client.get("/", headers={"X-Forwarded-Proto": "https"})\n            self.assertEqual(response.status_code, 200)\n            self.assertIn("max-age=31536000", response.headers.get("Strict-Transport-Security", ""))\n        finally:\n            self.crm.app.config["TRUST_PROXY_HEADERS"] = previous\n\n\n'''
    text = replace_once(text, anchor, replacement, "security controls regression tests")
    path.write_text(text, encoding="utf-8")


def patch_env_example():
    path = ROOT / ".env.example"
    text = path.read_text(encoding="utf-8")
    old = '''# Login throttling\nLOGIN_FAILURE_WINDOW_SECONDS=900\nLOGIN_MAX_FAILURES_PER_ACCOUNT=5\nLOGIN_MAX_FAILURES_PER_IP=20\n'''
    new = '''# Login throttling\nLOGIN_FAILURE_WINDOW_SECONDS=900\nLOGIN_MAX_FAILURES_PER_ACCOUNT=5\nLOGIN_MAX_FAILURES_PER_IP=20\n\n# Authenticated session limits\nSESSION_IDLE_MINUTES=30\nSESSION_ABSOLUTE_HOURS=12\n'''
    text = replace_once(text, old, new, "environment session controls")
    path.write_text(text, encoding="utf-8")


def main():
    patch_auth_hardening()
    patch_auth_tests()
    patch_env_example()


if __name__ == "__main__":
    main()
