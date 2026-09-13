from pathlib import Path

path = Path("auth_hardening.py")
text = path.read_text(encoding="utf-8")

old = '    "client_ip_address", "two_factor_policy_enabled", "two_factor_session_complete",\n'
new = '    "client_ip_address", "two_factor_policy_enabled", "two_factor_is_required", "two_factor_session_complete",\n'
if new not in text:
    if old not in text:
        raise SystemExit("Could not find core 2FA import marker")
    text = text.replace(old, new, 1)

text = text.replace(
    'and (not two_factor_policy_enabled() or two_factor_session_complete())',
    'and (not two_factor_is_required() or two_factor_session_complete())',
)
text = text.replace(
    'if not two_factor_policy_enabled() or two_factor_session_complete():',
    'if not two_factor_is_required() or two_factor_session_complete():',
)
text = text.replace(
    'if two_factor_policy_enabled() and not two_factor_session_complete():',
    'if two_factor_is_required() and not two_factor_session_complete():',
)

path.write_text(text, encoding="utf-8")
print("Aligned authentication lifecycle controls with the CRM effective 2FA gate.")
