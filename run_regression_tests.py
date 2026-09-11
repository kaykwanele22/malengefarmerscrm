"""Run Malenge CRM regression suites in isolated processes.

Each suite imports app.py with its own temporary DATABASE_URL. Running them in
separate processes prevents Python module caching from leaking one test database
into another, including the Phase 7 operations tests.
"""
from pathlib import Path
import subprocess
import sys

SUITES = [
    "full_regression_tests.py",
    "permission_regression_tests.py",
    "mobile_regression_tests.py",
    "security_regression_tests.py",
    "executive_regression_tests.py",
    "membership_regression_tests.py",
    "phase6_accountability_tests.py",
    "phase7_regression_tests.py",
]


def main():
    root = Path(__file__).resolve().parent
    failed = []
    for suite in SUITES:
        print(f"\n=== {suite} ===", flush=True)
        result = subprocess.run([sys.executable, str(root / suite)], cwd=root)
        if result.returncode != 0:
            failed.append(suite)
    if failed:
        print("\nFAILED: " + ", ".join(failed))
        return 1
    print("\nAll Malenge CRM regression suites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
