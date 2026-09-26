"""Operator commands: `python -m muse.cli create-user --username owner`."""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy.exc import IntegrityError

from muse.modules.auth.auth_handler import AuthHandler
from muse.shared.db import create_engine
from muse.shared.settings import get_settings

MIN_PASSWORD_LENGTH = 12


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("password: ")
    if first != getpass.getpass("again: "):
        sys.exit("passwords do not match")
    return first


async def _create_user(username: str, password: str) -> None:
    settings = get_settings()
    engine = create_engine(settings, pool_size=1)
    try:
        principal = await AuthHandler(engine, settings).create_user(username, password)
    except IntegrityError:
        sys.exit(f"user {username!r} already exists")
    finally:
        await engine.dispose()
    print(f"created {principal.username} ({principal.id})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="muse.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()

    password = _read_password(args.password_stdin)
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    asyncio.run(_create_user(args.username, password))


if __name__ == "__main__":
    main()
