from pathlib import Path
import re
from app import app

template_path = Path("templates/base.html")
text = template_path.read_text(encoding="utf-8")

endpoints = sorted(set(
    re.findall(r"url_for\(['\"]([^'\"]+)['\"]", text)
))

valid = set(app.view_functions)
invalid = [endpoint for endpoint in endpoints if endpoint not in valid]

print("ENDPOINTS IN BASE.HTML:")
for endpoint in endpoints:
    print(" -", endpoint)

print()
print("INVALID ENDPOINTS:", invalid)