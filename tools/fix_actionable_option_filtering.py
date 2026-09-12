from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "primary_production.py"
    text = path.read_text(encoding="utf-8")
    old = '    active_crops = [crop for crop in crops if crop.status not in {"Harvested", "Failed"}]\n'
    new = (
        '    active_crops = [\n'
        '        crop for crop in crops\n'
        '        if crop.status not in {"Harvested", "Failed"}\n'
        '        and (crop.id not in plan_by_crop or plan_by_crop[crop.id].status != "Completed")\n'
        '    ]\n'
    )
    if new in text:
        print("Primary production filtering already tightened.")
        return
    if old not in text:
        raise RuntimeError("Primary production active-crop anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Completed production programmes removed from routine crop action lists.")


if __name__ == "__main__":
    main()
