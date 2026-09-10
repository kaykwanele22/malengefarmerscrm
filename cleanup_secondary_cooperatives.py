from app import app, db, Cooperative

CORRECT_SECONDARY_NAME = "Malenge Secondary Cooperative"

with app.app_context():
    print("\nCURRENT COOPERATIVES")
    print("=" * 60)

    cooperatives = Cooperative.query.order_by(Cooperative.id).all()
    for cooperative in cooperatives:
        print(f"ID: {cooperative.id} | Name: {cooperative.name} | Type: {cooperative.cooperative_type} | Status: {cooperative.status}")

    correct_secondary = Cooperative.query.filter_by(name=CORRECT_SECONDARY_NAME, cooperative_type="Secondary").first()
    if not correct_secondary:
        print(f"\nERROR: Could not find '{CORRECT_SECONDARY_NAME}'.")
        print("Nothing was deleted.")
        raise SystemExit

    accidental_secondaries = Cooperative.query.filter(Cooperative.cooperative_type == "Secondary", Cooperative.id != correct_secondary.id).all()
    if not accidental_secondaries:
        print("\nNo duplicate Secondary Cooperatives found.")
        raise SystemExit

    print("\nSECONDARY COOPERATIVE TO KEEP")
    print("=" * 60)
    print(f"ID: {correct_secondary.id} | {correct_secondary.name}")

    print("\nACCIDENTAL SECONDARIES TO REMOVE")
    print("=" * 60)
    for cooperative in accidental_secondaries:
        print(f"ID: {cooperative.id} | {cooperative.name}")

    confirmation = input("\nType DELETE to remove these accidental Secondary Cooperatives: ")
    if confirmation != "DELETE":
        print("\nCancelled. Nothing was changed.")
        raise SystemExit

    for accidental in accidental_secondaries:
        # Move any Primary Cooperatives connected to the wrong Secondary
        children = Cooperative.query.filter_by(parent_id=accidental.id).all()
        for child in children:
            print(f"Moving {child.name} to {correct_secondary.name}")
            child.parent_id = correct_secondary.id

        # Move any CRM records attached to the accidental Secondary
        for table in db.metadata.sorted_tables:
            if table.name == "cooperative":
                continue
            if "cooperative_id" not in table.c:
                continue
            db.session.execute(
                table.update()
                .where(table.c.cooperative_id == accidental.id)
                .values(cooperative_id=correct_secondary.id)
            )

        print(f"Deleting accidental Secondary: {accidental.name}")
        db.session.delete(accidental)

    db.session.commit()

    print("\nCLEANUP COMPLETE")
    print("=" * 60)

    cooperatives = Cooperative.query.order_by(Cooperative.id).all()
    for cooperative in cooperatives:
        print(f"ID: {cooperative.id} | Name: {cooperative.name} | Type: {cooperative.cooperative_type}")

    print("\nExpected result:")
    print("1 Secondary Cooperative")
    print("2 Primary Cooperatives")
    print("3 Cooperatives total")