#!/usr/bin/env python3
"""Seed Gmail users with one-time passwords that force a reset on next sign-in."""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

import registration


def _prepare_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update Gmail users with a shared one-time password."
    )
    parser.add_argument(
        "emails",
        nargs="+",
        help="List of Gmail addresses to seed.",
    )
    parser.add_argument(
        "-p",
        "--password",
        help="One-time password to assign. If omitted, you will be prompted securely.",
    )
    return parser.parse_args()


def _seed_user(email: str, password_hash: str) -> None:
    email = email.strip().lower()
    if not registration._is_gmail_address(email):  # type: ignore[attr-defined]
        print(f"Skipping {email!r}: only Gmail addresses are supported.", file=sys.stderr)
        return

    user = registration.load_user(email)
    now = datetime.now(timezone.utc)
    if user:
        updated = registration.update_user_credentials(
            email,
            password_hash=password_hash,
            must_change_password=True,
        )
        if updated:
            print(f"Updated {email}")
        else:
            print(f"No changes applied to {email}", file=sys.stderr)
        return

    with registration.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            registration.users.insert().values(  # type: ignore[attr-defined]
                email=email,
                password_hash=password_hash,
                must_change_password=True,
                created_at=now,
                updated_at=now,
            )
        )
    print(f"Created {email}")


def main() -> int:
    args = _prepare_args()
    password = args.password or getpass.getpass("One-time password: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        return 1

    password_hash = generate_password_hash(password)
    for email in args.emails:
        _seed_user(email, password_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
