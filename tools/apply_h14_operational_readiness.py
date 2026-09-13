from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "app.py"
text = path.read_text(encoding="utf-8")

old = '''# Persistent login security, password lifecycle and account activity controls.\nfrom auth_hardening import register_auth_hardening\nregister_auth_hardening(app)\n\n\n# =========================================================\n# RUN APPLICATION\n# =========================================================\n'''
new = '''# Persistent login security, password lifecycle and account activity controls.\nfrom auth_hardening import register_auth_hardening\nregister_auth_hardening(app)\n\n# Deployment liveness/readiness probes verify the process, database and protected evidence storage.\nfrom operational_readiness import register_operational_readiness\nregister_operational_readiness(app)\n\n\n# =========================================================\n# RUN APPLICATION\n# =========================================================\n'''

if old not in text:
    raise RuntimeError("Could not find application registration anchor for operational readiness")

path.write_text(text.replace(old, new, 1), encoding="utf-8")
