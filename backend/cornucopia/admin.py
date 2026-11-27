"""Operator administration: ``python -m cornucopia.admin create-operator``.

Runs where the API runs (the Sprite), through the same connector. Passwords
are read from stdin or generated; only the argon2id hash is stored. A
generated password is printed exactly once.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from cornucopia.auth import hash_password
from cornucopia.config import get_settings
from cornucopia.persistence.factory import build_client
from cornucopia.persistence.repositories.operations import SupabaseOperationsRepository


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cornucopia.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-operator", help="create or update an operator")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=["viewer", "operator", "approver", "admin"], required=True)
    c.add_argument(
        "--generate-password",
        action="store_true",
        help="generate a strong password and print it once",
    )
    c.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    args = ap.parse_args(argv)

    if args.generate_password:
        password = secrets.token_urlsafe(18)
    elif args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("password: ")
    settings = get_settings()
    db = build_client(settings)
    repo = SupabaseOperationsRepository(db)
    org = repo.ensure_organization(settings.org_slug, settings.org_name)
    out = repo.call(
        "create_operator",
        {
            "p_organization_id": str(org.id),
            "p_username": args.username,
            "p_display_name": args.name,
            "p_role": args.role,
            "p_password_hash": hash_password(password),
        },
    )
    print(f"operator {out['username']} ({out['role']}) ready in {org.slug}")
    if args.generate_password:
        print(f"generated password (shown once): {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
