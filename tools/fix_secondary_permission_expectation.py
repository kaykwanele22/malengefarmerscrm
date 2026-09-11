from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "permission_regression_tests.py"


def main():
    text = PATH.read_text(encoding="utf-8")
    marker = "    def test_secondary_chair_cannot_approve_primary_finance(self):\n"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError("Secondary Chairperson finance test not found")
    end = text.find("\n    # ---------------------------------------------------------", start)
    if end < 0:
        end = len(text)
    block = text[start:end]
    if "            404,\n" in block:
        print("Strict-scope expectation already updated.")
        return
    old = "            403,\n"
    if old not in block:
        raise RuntimeError("Expected 403 assertion not found in Secondary Chairperson test")
    block = block.replace(old, "            404,\n", 1)
    PATH.write_text(text[:start] + block + text[end:], encoding="utf-8")
    print("Secondary Chairperson strict-scope expectation updated to 404.")


if __name__ == "__main__":
    main()
