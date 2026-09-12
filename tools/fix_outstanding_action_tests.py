from pathlib import Path

path = Path(__file__).resolve().parents[1] / "outstanding_action_regression_tests.py"
text = path.read_text(encoding="utf-8")
old = "self.assertEqual(response.status_code, 400)"
count = text.count(old)
if count:
    path.write_text(text.replace(old, "self.assertEqual(response.status_code, 303)"), encoding="utf-8")
    print(f"Updated {count} validation redirect assertions.")
else:
    print("Outstanding action tests already use validation redirect expectations.")
