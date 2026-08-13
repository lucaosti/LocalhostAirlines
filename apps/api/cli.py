"""Operator CLI for account bootstrap.

There is no public registration endpoint (docs/api.md never defines one):
this is a single-operator personal system reached only from a trusted LAN
(spec §7, README "Contributing"), not a multi-tenant service. Someone still
has to be able to create the first account, so that happens here instead —
run inside the container, never over the network:

    docker compose exec api python -m apps.api.cli create-user \\
        --username luca --email luca@example.com --role ADMIN
"""

import argparse
import asyncio
import getpass
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from domain.users.passwords import hash_password
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models import Role, User


async def create_user(username: str, email: str, role: Role) -> None:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)

    async with session_scope() as db:
        existing = await db.execute(
            select(User).where((User.username == username) | (User.email == email))
        )
        if existing.scalar_one_or_none() is not None:
            print(
                f"A user with username '{username}' or email '{email}' already exists.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        now = datetime.now(UTC)
        db.add(
            User(
                id=uuid.uuid4(),
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=role,
                created_at=now,
                updated_at=now,
            )
        )

    print(f"Created {role.value.lower()} user '{username}'.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="apps.api.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-user", help="Create a new user account")
    create.add_argument("--username", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=["USER", "ADMIN"], default="USER")

    args = parser.parse_args()

    if args.command == "create-user":
        asyncio.run(create_user(args.username, args.email, Role[args.role]))


if __name__ == "__main__":
    main()
