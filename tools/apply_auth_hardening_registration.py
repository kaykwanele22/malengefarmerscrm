from pathlib import Path

path = Path("app.py")
text = path.read_text(encoding="utf-8")
marker = '''# Cooperative cash, bank and other account balances.\nfrom account_ledger import register_account_ledger\nregister_account_ledger(app)\n'''
addition = marker + '''\n# Persistent login security, password lifecycle and account activity controls.\nfrom auth_hardening import register_auth_hardening\nregister_auth_hardening(app)\n'''

if "from auth_hardening import register_auth_hardening" in text:
    print("Authentication hardening is already registered.")
elif marker not in text:
    raise SystemExit("Could not find the account-ledger registration marker in app.py")
else:
    path.write_text(text.replace(marker, addition, 1), encoding="utf-8")
    print("Registered auth_hardening in app.py")
