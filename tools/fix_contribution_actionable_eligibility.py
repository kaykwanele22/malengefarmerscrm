from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "app.py"
    text = path.read_text(encoding="utf-8")
    old = '''    eligible_memberships = (
        Membership.query
        .join(Farmer, Farmer.id == Membership.farmer_id)
        .filter(
            Membership.cooperative_id == access.cooperative_id,
            Membership.status.notin_(["Resigned", "Deceased", "Inactive"]),
        )
        .order_by(Farmer.fullname.asc())
        .all()
    )
    eligible_memberships = [m for m in eligible_memberships if m.fee_outstanding > 1e-9]
    farmers = [m.farmer for m in eligible_memberships]
    eligible_farmer_ids = {farmer.id for farmer in farmers}
    selected_membership = None
'''
    new = '''    own_farmers = own_cooperative_query(Farmer).order_by(Farmer.fullname.asc()).all()
    active_memberships = (
        Membership.query
        .filter(
            Membership.cooperative_id == access.cooperative_id,
            Membership.status.notin_(["Resigned", "Deceased", "Inactive"]),
        )
        .all()
    )
    membership_by_farmer_id = {membership.farmer_id: membership for membership in active_memberships}
    farmers = [
        farmer for farmer in own_farmers
        if farmer.id not in membership_by_farmer_id
        or membership_by_farmer_id[farmer.id].fee_outstanding > 1e-9
    ]
    eligible_farmer_ids = {farmer.id for farmer in farmers}
    selected_membership = None
'''
    if new in text:
        print("Contribution eligibility already preserves generic contributors.")
        return
    if old not in text:
        raise RuntimeError("Patched contribution eligibility anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Generic contributors remain selectable; completed active memberships are hidden.")


if __name__ == "__main__":
    main()
