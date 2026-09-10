"""Trusted maintenance reset for a user who lost Google Authenticator and recovery codes.

Usage:
    python reset_user_2fa.py user@example.com

Run this only from a trusted server/local administration environment.
The user will be forced to enroll Google Authenticator again at the next login.
"""
import sys

from app import User, app, clear_user_two_factor, db, utc_now, AuditLog


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python reset_user_2fa.py user@example.com")

    email = sys.argv[1].strip().lower()
    with app.app_context():
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if not user:
            raise SystemExit(f"No CRM user found for {email}")

        clear_user_two_factor(user)
        db.session.add(AuditLog(
            user_id=user.id,
            cooperative_id=user.access_record.cooperative_id if user.access_record else None,
            action="TWO_FACTOR_TRUSTED_RESET",
            entity_type="User",
            entity_id=user.id,
            details="Google Authenticator enrollment reset from trusted maintenance script.",
            created_at=utc_now(),
        ))
        db.session.commit()
        print(f"Google Authenticator reset for {email}. The account must enroll again at next sign-in.")


if __name__ == "__main__":
    main()
