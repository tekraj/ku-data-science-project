from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from nepse_common.config import load_app_config
from nepse_common.db.session import session_scope
from nepse_common.models import AdminUser
from nepse_common.security import hash_password


def create_admin(email: str, password: str, display_name: str | None) -> int:
    normalized_email = email.strip().lower()
    if not normalized_email:
        print("Email must not be empty.", file=sys.stderr)
        return 1
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1

    config = load_app_config()
    with session_scope(config.database) as db:
        existing = db.execute(
            select(AdminUser).where(AdminUser.email == normalized_email)
        ).scalar_one_or_none()

        if existing is not None:
            existing.password_hash = hash_password(password)
            existing.display_name = display_name or existing.display_name
            existing.is_active = True
            print(f"Updated existing admin user: {normalized_email}")
        else:
            db.add(
                AdminUser(
                    email=normalized_email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    is_active=True,
                )
            )
            print(f"Created admin user: {normalized_email}")

    return 0


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match, try again.\n", file=sys.stderr)
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description="api-service management commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create-admin", help="Create or reset a dashboard admin login (no signup endpoint exists)."
    )
    create_parser.add_argument("--email", help="Admin login email. Prompted if omitted.")
    create_parser.add_argument(
        "--password",
        help="Admin login password. Prompted (hidden, with confirmation) if omitted -- "
        "avoid passing this on the command line where it may be recorded in shell history.",
    )
    create_parser.add_argument("--display-name", default=None, help="Optional display name shown in the dashboard.")

    args = parser.parse_args()

    if args.command == "create-admin":
        email = args.email or input("Email: ")
        password = args.password or _prompt_password()
        return create_admin(email, password, args.display_name)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
