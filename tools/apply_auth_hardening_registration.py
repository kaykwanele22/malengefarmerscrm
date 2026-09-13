from pathlib import Path


def replace_once(path, old, new, label):
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"{label} already applied.")
        return
    if old not in text:
        raise SystemExit(f"Could not find patch marker for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Applied {label}.")


app_path = Path("app.py")
app_text = app_path.read_text(encoding="utf-8")
marker = '''# Cooperative cash, bank and other account balances.\nfrom account_ledger import register_account_ledger\nregister_account_ledger(app)\n'''
addition = marker + '''\n# Persistent login security, password lifecycle and account activity controls.\nfrom auth_hardening import register_auth_hardening\nregister_auth_hardening(app)\n'''

if "from auth_hardening import register_auth_hardening" in app_text:
    print("Authentication hardening is already registered.")
elif marker not in app_text:
    raise SystemExit("Could not find the account-ledger registration marker in app.py")
else:
    app_path.write_text(app_text.replace(marker, addition, 1), encoding="utf-8")
    print("Registered auth_hardening in app.py")

user_form = Path("templates/user_form.html")
text = user_form.read_text(encoding="utf-8")
if 'minlength="8"' in text:
    text = text.replace('minlength="8"', 'minlength="10"')
if '<span class="form-help">At least 8 characters.</span>' in text:
    text = text.replace(
        '<span class="form-help">At least 8 characters.</span>',
        '<span class="form-help">At least 10 characters with uppercase, lowercase, a number and a symbol.</span>',
        1,
    )
old_note = '''            <div class="form-note">\n                This page creates a <strong>CRM login</strong>. It does not register a cooperative member.\n                Cooperative membership remains the Secretary's responsibility.\n            </div>'''
new_note = '''            <div class="form-note">\n                This page creates a <strong>CRM login</strong>. It does not register a cooperative member.\n                Cooperative membership remains the Secretary's responsibility. The password entered here is temporary:\n                the user must replace it with their own password at first sign-in.\n            </div>'''
if old_note in text:
    text = text.replace(old_note, new_note, 1)
user_form.write_text(text, encoding="utf-8")
print("Updated CRM user creation password guidance.")

users = Path("templates/users.html")
text = users.read_text(encoding="utf-8")
css_old = '.user-tool.twofa{background:#eef7ff;border-color:#cfe0ef;color:#2b5f84}\n'
css_new = css_old + '.user-tool.security{background:#f0f7f2;border-color:#cfe3d5;color:#285b3a}\n'
if '.user-tool.security{' not in text:
    if css_old not in text:
        raise SystemExit("Could not find Users page security-link CSS marker")
    text = text.replace(css_old, css_new, 1)

loop_old = '''    {% for user in users %}\n    {% set access = access_map.get(user.id) %}\n    {% if access %}'''
loop_new = '''    {% for user in users %}\n    {% set access = access_map.get(user.id) %}\n    {% set security = auth_security_state(user.id) %}\n    {% if access %}'''
if '{% set security = auth_security_state(user.id) %}' not in text:
    if loop_old not in text:
        raise SystemExit("Could not find Users page card-loop marker")
    text = text.replace(loop_old, loop_new, 1)

badge_old = '''                <span class="access-badge {% if not two_factor_policy_enabled() %}pending{% elif user.two_factor_enabled %}active{% else %}pending{% endif %}">2FA {{ 'Paused' if not two_factor_policy_enabled() else ('Enabled' if user.two_factor_enabled else 'Required') }}</span>\n                {% else %}'''
badge_new = '''                <span class="access-badge {% if not two_factor_policy_enabled() %}pending{% elif user.two_factor_enabled %}active{% else %}pending{% endif %}">2FA {{ 'Paused' if not two_factor_policy_enabled() else ('Enabled' if user.two_factor_enabled else 'Required') }}</span>\n                {% if security.locked %}<span class="access-badge inactive">Login Locked</span>{% elif security.must_change_password %}<span class="access-badge pending">Password Change Required</span>{% endif %}\n                {% else %}'''
if 'Password Change Required' not in text:
    if badge_old not in text:
        raise SystemExit("Could not find Users page badge marker")
    text = text.replace(badge_old, badge_new, 1)

link_old = '''            <a href="{{ url_for('reset_user_password', user_id=user.id) }}" class="user-tool password">Reset Password</a>\n            {% if user.two_factor_enabled'''
link_new = '''            <a href="{{ url_for('reset_user_password', user_id=user.id) }}" class="user-tool password">Reset Password</a>\n            <a href="{{ url_for('authsec.user_security_history', user_id=user.id) }}" class="user-tool security">Security &amp; Activity</a>\n            {% if user.two_factor_enabled'''
if 'authsec.user_security_history' not in text:
    if link_old not in text:
        raise SystemExit("Could not find Users page tools marker")
    text = text.replace(link_old, link_new, 1)

users.write_text(text, encoding="utf-8")
print("Added per-user security state and activity navigation.")
