#!/usr/bin/env python3
"""Command-line administration.

milsurp init                     create the schema, seed sites and the admin
milsurp secrets                  print fresh values for the config file
milsurp sites                    list sites and their schedules
milsurp scan [--site SLUG]       scan one site, or every enabled site
milsurp users                    list accounts
milsurp adduser NAME EMAIL       create an account (prompts for a password)
milsurp passwd NAME              change an account's password
milsurp digest [--user NAME]     send digests that are due, or one now
milsurp prune-images             delete image files no listing references
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select

from app.config import find_config_file, generate_secret, get_config
from app.database import session_scope
from app.models import (
    EmailPreference,
    Item,
    ItemPhoto,
    Site,
    User,
    UserRole,
)
from app.security import (
    PasswordPolicyError,
    hash_password,
    validate_password,
)
from app.services import bootstrap, scan_service
from app.services import digest as digest_service
from app.services.image_store import ImageStore


def _fmt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "never"


def cmd_init(_args: argparse.Namespace) -> int:
    config = get_config()
    print(f"Mode:      {config.mode}")
    print(f"Config:    {config.source_path or 'built-in defaults (no file found)'}")
    print(f"Database:  {config.database_path}")
    print(f"Images:    {config.images_path}")
    bootstrap.initialize(config)
    with session_scope() as session:
        sites = session.execute(select(Site)).scalars().all()
        admins = session.execute(select(User).where(User.role == UserRole.ADMIN)).scalars().all()
    print(f"Sites registered: {len(sites)}")
    print(f"Administrators:   {len(admins)}")

    # The most confusing first-run failure: an admin already exists from an
    # earlier run, so admin.password in the config was never applied, and
    # signing in with it returns 401 with no explanation anywhere.
    if admins and config.admin.password:
        from app.services.bootstrap import seed_password_differs

        with session_scope() as session:
            current = session.get(User, admins[0].id)
            if current is not None and seed_password_differs(current, config):
                print()
                print(
                    f"NOTE: {current.username!r} already existed, so admin.password "
                    f"from the config was NOT applied."
                )
                print(f"      To set it now:  backend/cli.py passwd {current.username}")
    if not admins:
        print(
            "\nNo administrator exists. Set admin.password in the config file and "
            "re-run 'make init', or create one with 'milsurp adduser'.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_secrets(_args: argparse.Namespace) -> int:
    """Print fresh secrets to paste into the config file."""
    print("# Paste into the 'security' section of your config.yaml:")
    print("security:")
    print(f"  password_pepper: {generate_secret()!r}")
    print(f"  jwt_secret: {generate_secret()!r}")
    print()
    print("# Changing password_pepper invalidates every existing password.")
    print("# Changing jwt_secret signs everyone out.")
    return 0


def cmd_sites(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        sites = session.execute(select(Site).order_by(Site.name)).scalars().all()
        if not sites:
            print("No sites registered. Run 'make init'.")
            return 0
        print(f"{'SLUG':<16} {'NAME':<24} {'ON':<4} {'EVERY':<9} {'LAST SCAN':<22} ITEMS")
        print("-" * 92)
        for site in sites:
            count = (
                session.execute(
                    select(Item).where(Item.site_id == site.id, Item.is_active.is_(True))
                )
                .scalars()
                .all()
            )
            interval = f"{site.scan_interval_minutes}m"
            if site.scan_interval_minutes % 60 == 0:
                interval = f"{site.scan_interval_minutes // 60}h"
            print(
                f"{site.slug:<16} {site.name[:23]:<24} "
                f"{'yes' if site.enabled else 'no':<4} {interval:<9} "
                f"{_fmt(site.last_scan_at):<22} {len(count)}"
            )
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    with session_scope() as session:
        if args.site:
            site = session.execute(select(Site).where(Site.slug == args.site)).scalars().first()
            if site is None:
                print(f"No site with slug {args.site!r}.", file=sys.stderr)
                return 1
            targets = [(site.id, site.name)]
        else:
            targets = [
                (site.id, site.name)
                for site in session.execute(
                    select(Site).where(Site.enabled.is_(True), Site.is_available.is_(True))
                )
                .scalars()
                .all()
            ]

    if not targets:
        print("Nothing to scan: no sites are enabled.")
        return 0

    failures = 0
    for site_id, name in targets:
        print(f"\n=== Scanning {name} ===")
        try:
            run_id = scan_service.run_scan(site_id, trigger="cli")
        except scan_service.ScanBusy as exc:
            print(f"  skipped: {exc}")
            continue
        with session_scope() as session:
            from app.models import ScanRun

            run = session.get(ScanRun, run_id)
            print(f"  status:    {run.status.value}")
            print(f"  found:     {run.items_found}")
            print(f"  new:       {run.items_new}")
            print(f"  updated:   {run.items_updated}")
            print(f"  de-listed: {run.items_delisted}")
            print(f"  price chg: {run.price_changes} ({run.price_drops} drops)")
            print(f"  images:    {run.images_downloaded}")
            print(f"  duration:  {run.duration_seconds}s")
            if run.error_message:
                print(f"  note:      {run.error_message}")
            if run.status.value in ("failed", "canceled"):
                failures += 1
    return 1 if failures else 0


def cmd_users(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        users = session.execute(select(User).order_by(User.username)).scalars().all()
        print(f"{'USERNAME':<20} {'ROLE':<8} {'ACTIVE':<7} {'EMAIL':<32} LAST LOGIN")
        print("-" * 96)
        for user in users:
            print(
                f"{user.username:<20} {user.role.value:<8} "
                f"{'yes' if user.is_active else 'no':<7} {user.email[:31]:<32} "
                f"{_fmt(user.last_login_at)}"
            )
    return 0


def _prompt_password() -> str | None:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm:  "):
        print("Passwords do not match.", file=sys.stderr)
        return None
    try:
        validate_password(password, get_config())
    except PasswordPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return None
    return password


def cmd_adduser(args: argparse.Namespace) -> int:
    password = args.password or _prompt_password()
    if not password:
        return 1
    config = get_config()
    with session_scope() as session:
        clash = (
            session.execute(
                select(User).where((User.username == args.username) | (User.email == args.email))
            )
            .scalars()
            .first()
        )
        if clash is not None:
            print("That username or email address is already in use.", file=sys.stderr)
            return 1
        user = User(
            username=args.username,
            email=args.email,
            full_name=args.full_name,
            password_hash=hash_password(password, config),
            role=UserRole.ADMIN if args.admin else UserRole.NORMAL,
        )
        session.add(user)
        session.flush()
        session.add(EmailPreference(user_id=user.id))
    print(f"Created {'admin' if args.admin else 'normal'} user {args.username!r}.")
    return 0


def cmd_passwd(args: argparse.Namespace) -> int:
    password = args.password or _prompt_password()
    if not password:
        return 1
    config = get_config()
    with session_scope() as session:
        user = session.execute(select(User).where(User.username == args.username)).scalars().first()
        if user is None:
            print(f"No user named {args.username!r}.", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password, config)
        # Sign the account out everywhere.
        user.token_version += 1
    print(f"Password updated for {args.username!r}; existing sessions were ended.")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    config = get_config()
    with session_scope() as session:
        if args.user:
            user = session.execute(select(User).where(User.username == args.user)).scalars().first()
            if user is None:
                print(f"No user named {args.user!r}.", file=sys.stderr)
                return 1
            user_ids = [user.id]
        else:
            user_ids = digest_service.due_user_ids(session)

    if not user_ids:
        print("No digests are due.")
        return 0

    for user_id in user_ids:
        with session_scope() as session:
            user = session.get(User, user_id)
            result = digest_service.send_digest_for_user(
                session, user, config, force=bool(args.user)
            )
            line = f"{user.username}: {result.status.value}"
            if result.status.value == "sent":
                line += f" ({result.new_item_count} new, {result.price_drop_count} drops)"
            elif result.error_message:
                line += f" — {result.error_message}"
            print(line)
    return 0


def cmd_prune_images(_args: argparse.Namespace) -> int:
    config = get_config()
    store = ImageStore(config)
    with session_scope() as session:
        known = set(
            session.execute(select(ItemPhoto.filename).where(ItemPhoto.filename.is_not(None)))
            .scalars()
            .all()
        )
    before = store.usage_bytes()
    removed = store.prune_orphans(known)
    after = store.usage_bytes()
    print(f"Removed {removed} orphaned file(s); reclaimed {(before - after) / 1e6:.1f} MB.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="milsurp",
        description="Milsurp Monitor administration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", help="Path to a config.yaml (overrides the search path).")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the schema and seed sites/admin.").set_defaults(
        func=cmd_init
    )
    sub.add_parser("secrets", help="Generate config secrets.").set_defaults(func=cmd_secrets)
    sub.add_parser("sites", help="List sites.").set_defaults(func=cmd_sites)

    scan = sub.add_parser("scan", help="Scan one site or every enabled site.")
    scan.add_argument("--site", help="Site slug; omit to scan all enabled sites.")
    scan.set_defaults(func=cmd_scan)

    sub.add_parser("users", help="List accounts.").set_defaults(func=cmd_users)

    adduser = sub.add_parser("adduser", help="Create an account.")
    adduser.add_argument("username")
    adduser.add_argument("email")
    adduser.add_argument("--full-name")
    adduser.add_argument("--admin", action="store_true", help="Make it an administrator.")
    adduser.add_argument("--password", help="Set non-interactively (avoid in shared shells).")
    adduser.set_defaults(func=cmd_adduser)

    passwd = sub.add_parser("passwd", help="Change an account's password.")
    passwd.add_argument("username")
    passwd.add_argument("--password", help="Set non-interactively.")
    passwd.set_defaults(func=cmd_passwd)

    digest_cmd = sub.add_parser("digest", help="Send due digests.")
    digest_cmd.add_argument("--user", help="Send to one user now, even if not due.")
    digest_cmd.set_defaults(func=cmd_digest)

    sub.add_parser("prune-images", help="Delete image files no listing references.").set_defaults(
        func=cmd_prune_images
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config:
        import os

        os.environ["MILSURP_CONFIG"] = args.config
        get_config(reload=True)
    if find_config_file() is None:
        print(
            "Note: no config.yaml found; using built-in defaults.",
            file=sys.stderr,
        )
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
