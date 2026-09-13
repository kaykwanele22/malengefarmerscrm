from pathlib import Path


def replace_once(path, old, new, label):
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"{label} already applied")
        return
    if old not in text:
        raise SystemExit(f"Could not find marker for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Applied {label}")


auth = Path("auth_hardening.py")
replace_once(
    auth,
    '''    session["auth_version"] = int(security.auth_version or 1)\n    db.session.commit()\n    return security\n''',
    '''    session["auth_version"] = int(security.auth_version or 1)\n    session["_auth_login_recorded_for"] = user.id\n    db.session.commit()\n    return security\n''',
    "authenticated-login session marker",
)
replace_once(
    auth,
    '''    elif int(session_version) != current_version:\n        session.clear()\n        return redirect(url_for("login"))\n\n    exempt = {\n''',
    '''    elif int(session_version) != current_version:\n        session.clear()\n        return redirect(url_for("login"))\n\n    # Flask saves the session after response hooks, so the login POST may not expose\n    # its freshly-created session to this module's after_request callback. Record a\n    # successful login exactly once on the first subsequent authenticated request.\n    # Second-factor challenge endpoints are excluded so this never treats an\n    # unfinished Google Authenticator challenge as a completed login.\n    endpoint = request.endpoint or ""\n    if (\n        session.get("_auth_login_recorded_for") != user.id\n        and endpoint not in {"two_factor_setup", "two_factor_verify"}\n        and (not two_factor_policy_enabled() or two_factor_session_complete())\n    ):\n        security = _mark_authenticated_login(user)\n\n    exempt = {\n''',
    "first authenticated request login tracking",
)

tests = Path("auth_hardening_regression_tests.py")
replace_once(
    tests,
    '''        self.assertIn(response.status_code, {302, 303})\n        with self.crm.app.app_context():\n            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()\n''',
    '''        self.assertIn(response.status_code, {302, 303})\n        dashboard = self.client.get(\n            "/dashboard",\n            headers={"User-Agent": "AuthLifecycleRegression/1.0"},\n            follow_redirects=False,\n        )\n        self.assertEqual(dashboard.status_code, 200)\n        with self.crm.app.app_context():\n            security = self.auth.UserSecurity.query.filter_by(user_id=self.treasurer_id).one()\n''',
    "login activity regression follow-up request",
)
