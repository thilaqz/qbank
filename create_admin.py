"""Create or reset the QBank administrator account.

Run once after the schema is in place:

    python create_admin.py

The password is never stored as typed. Werkzeug hashes it with PBKDF2 and a
per-account salt, and only that hash reaches the database.
"""

import getpass
import sys

from werkzeug.security import generate_password_hash

import db
import repository as repo


def main() -> int:
    print("QBank administrator setup\n")

    if not db.healthy():
        print("The database did not answer. Check .env and that Oracle is running.")
        return 1

    username = input("Username: ").strip()
    if not username:
        print("A username is required.")
        return 1

    full_name = input("Full name (optional): ").strip() or None

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Use at least 8 characters.")
        return 1
    if password != getpass.getpass("Repeat password: "):
        print("The two passwords do not match.")
        return 1

    password_hash = generate_password_hash(password)
    existing = repo.get_admin_by_username(username)

    if existing:
        answer = input(f"{username} already exists. Reset the password? [y/N] ")
        if answer.strip().lower() != "y":
            print("Nothing changed.")
            return 0
        db.execute(
            """
            UPDATE admin_users
            SET    password_hash = :password_hash,
                   full_name     = NVL(:full_name, full_name)
            WHERE  admin_id = :admin_id
            """,
            {
                "password_hash": password_hash,
                "full_name": full_name,
                "admin_id": int(existing["admin_id"]),
            },
        )
        print(f"Password reset for {username}.")
        return 0

    db.execute(
        """
        INSERT INTO admin_users (username, password_hash, full_name)
        VALUES (:username, :password_hash, :full_name)
        """,
        {
            "username": username,
            "password_hash": password_hash,
            "full_name": full_name,
        },
    )
    print(f"Administrator {username} created. Sign in at /admin/login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
