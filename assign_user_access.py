from app import app, db, User, UserAccess, Cooperative

ROLES = [
    "Admin",
    "Secondary Chairperson",
    "Secondary Vice Chairperson",
    "Secondary Secretary",
    "Secondary Vice Secretary",
    "Secondary Treasurer",
    "Primary Chairperson",
    "Primary Vice Chairperson",
    "Primary Secretary",
    "Primary Vice Secretary",
    "Primary Treasurer",
]

def print_users():
    users = User.query.order_by(User.id.asc()).all()
    print("\nUSERS")
    print("-" * 70)
    for user in users:
        access = UserAccess.query.filter_by(user_id=user.id).first()
        role = access.role if access else "No access record"
        cooperative = access.cooperative.name if access and access.cooperative else "Unassigned"
        status = access.status if access else "N/A"
        print(f"ID {user.id} | {user.fullname} | {user.email} | {role} | {cooperative} | {status}")

def print_cooperatives():
    cooperatives = Cooperative.query.order_by(Cooperative.cooperative_type.desc(), Cooperative.name.asc()).all()
    print("\nCOOPERATIVES")
    print("-" * 70)
    for cooperative in cooperatives:
        print(f"ID {cooperative.id} | {cooperative.name} | {cooperative.cooperative_type} | {cooperative.status}")

def print_roles():
    print("\nAVAILABLE ROLES")
    print("-" * 70)
    for index, role in enumerate(ROLES, start=1):
        print(f"{index}. {role}")

def main():
    with app.app_context():
        print("\n")
        print("=" * 70)
        print("MALENGE FARMERS CRM")
        print("USER ACCESS ASSIGNMENT")
        print("=" * 70)

        print_users()
        print_cooperatives()
        print_roles()

        print("\n" + "=" * 70)

        try:
            user_id = int(input("\nEnter the USER ID you want to configure: ").strip())
        except ValueError:
            print("Invalid user ID.")
            return

        user = db.session.get(User, user_id)
        if not user:
            print("User not found.")
            return

        print_roles()

        try:
            role_number = int(input("\nSelect the ROLE number: ").strip())
        except ValueError:
            print("Invalid role.")
            return

        if role_number < 1 or role_number > len(ROLES):
            print("Invalid role selection.")
            return

        selected_role = ROLES[role_number - 1]
        cooperative_id = None

        if selected_role != "Admin":
            print_cooperatives()
            try:
                cooperative_id = int(input("\nEnter the COOPERATIVE ID: ").strip())
            except ValueError:
                print("Invalid cooperative ID.")
                return

            cooperative = db.session.get(Cooperative, cooperative_id)
            if not cooperative:
                print("Cooperative not found.")
                return

            if selected_role.startswith("Secondary") and cooperative.cooperative_type != "Secondary":
                print("A Secondary role must be assigned to the Secondary Cooperative.")
                return

            if selected_role.startswith("Primary") and cooperative.cooperative_type != "Primary":
                print("A Primary role must be assigned to a Primary Cooperative.")
                return

        access = UserAccess.query.filter_by(user_id=user.id).first()
        if not access:
            access = UserAccess(user_id=user.id)
            db.session.add(access)

        access.role = selected_role
        access.cooperative_id = cooperative_id
        access.status = "Active"
        db.session.commit()

        print("\n" + "=" * 70)
        print("ACCESS UPDATED")
        print("=" * 70)
        print(f"User: {user.fullname}")
        print(f"Email: {user.email}")
        print(f"Role: {access.role}")
        if access.cooperative:
            print(f"Cooperative: {access.cooperative.name}")
        else:
            print("Cooperative: System-wide")
        print(f"Status: {access.status}")
        print("\nAssignment completed successfully.")

if __name__ == "__main__":
    main()