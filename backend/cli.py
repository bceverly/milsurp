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
import re
import sys
from datetime import UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, select

from app.config import find_config_file, generate_secret, get_config
from app.database import session_scope
from app.models import (
    EmailPreference,
    Item,
    ItemPhoto,
    ScanRun,
    ScanStatus,
    Site,
    User,
    UserRole,
    utcnow,
)
from app.security import (
    PasswordPolicyError,
    hash_password,
    validate_password,
)
from app.services import backup as backup_service
from app.services import bootstrap, classify, crosscatalog, manufacturers, scan_service
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


#: The settings this command manages, and what changing one costs.
_SECRET_SETTINGS = (
    ("password_pepper", "every existing password stops verifying"),
    ("jwt_secret", "everyone signed in is signed out"),
)


#: A YAML scalar on its own line: `  jwt_secret: "value"`.
#:
#: Horizontal whitespace only, deliberately: `\s` matches a newline too, so a
#: greedy `\s*` after the colon ran past the end of an empty setting and read
#: the *next* line as its value — which made `jwt_secret:` with nothing after
#: it look like a secret that was already set.
_SETTING_LINE = r"^([^\S\n]*{name}:[^\S\n]*)(.*)$"


def _is_set(text: str, name: str) -> bool:
    """Whether a setting already holds a real value rather than a placeholder.

    The value is pulled out and examined rather than tested with a lookahead
    inside the line pattern: an optional quote plus a negative lookahead lets
    the regex engine backtrack past the quote and declare "CHANGE-ME" a real
    secret, which is exactly what it did.
    """
    match = re.search(_SETTING_LINE.format(name=name), text, re.MULTILINE)
    if not match:
        return False
    value = match.group(2).strip().strip("\"'").strip()
    return bool(value) and not value.startswith("CHANGE-ME")


def cmd_secrets(args: argparse.Namespace) -> int:
    """Generate fresh secrets and write them into the config file.

    Written, not printed. Printing them was the obvious design — the operator
    pastes them where they belong — but it puts two live credentials into a
    terminal, a scrollback buffer, and whatever records that terminal: a shell
    log, a screen recording, a support ticket with a screenshot in it. Writing
    them straight to the file they are for is fewer steps *and* the value never
    exists anywhere the operator did not choose.

    Refuses to overwrite secrets that are already set, because both of these
    are destructive to change and the destruction is silent until the next
    person tries to sign in.
    """
    path = find_config_file()
    if path is None:
        print(
            "No configuration file found. Copy config.yaml.sample to config.yaml "
            "(or run 'make config') and try again.",
            file=sys.stderr,
        )
        return 1

    text = path.read_text(encoding="utf-8")
    already_set = [name for name, _cost in _SECRET_SETTINGS if _is_set(text, name)]
    if already_set and not args.force:
        print(f"{path} already has: {', '.join(already_set)}.", file=sys.stderr)
        print("Rotating them is destructive:", file=sys.stderr)
        for name, cost in _SECRET_SETTINGS:
            print(f"  {name}: {cost}", file=sys.stderr)
        print("Re-run with --force if that is what you want.", file=sys.stderr)
        return 1

    written = []
    for name, _cost in _SECRET_SETTINGS:
        replacement, count = re.subn(
            _SETTING_LINE.format(name=name),
            lambda match: f'{match.group(1)}"{generate_secret()}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count:
            text, _ = replacement, written.append(name)
        else:
            print(f"Could not find a '{name}:' line in {path}.", file=sys.stderr)
            return 1

    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)

    print(f"Wrote {', '.join(written)} to {path} (mode 600).")
    print("The values are in the file; they are deliberately not printed here.")
    if args.force and already_set:
        for name, cost in _SECRET_SETTINGS:
            print(f"  {name} changed: {cost}.")
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


def cmd_fetch_photos(args: argparse.Namespace) -> int:
    """Drain the photo download queue without re-scraping anything."""
    downloaded = scan_service.download_pending_photos(
        site_slug=args.site, limit=args.limit, progress=lambda message: print(f"  {message}")
    )
    if not downloaded:
        print("No photos are waiting to be downloaded.")
    else:
        print(f"Downloaded {downloaded} photo(s).")
    return 0


def cmd_reclassify(_args: argparse.Namespace) -> int:
    """Re-derive rifle/pistol and the other inferred fields from stored text.

    Classification runs on every upsert, so a re-scan fixes it — but a re-scan
    of a large catalog is a quarter of an hour of somebody else's bandwidth for
    a change that needs no network at all. This re-runs the heuristics over
    what is already in the database.
    """
    changed = 0
    with session_scope() as session:
        # Whether a site's prose is about the listing it is attached to. Looked
        # up once per site rather than once per listing.
        trusted = {
            site.id: scan_service.descriptions_are_reliable(site.slug)
            for site in session.execute(select(Site)).scalars()
        }
        items = session.execute(select(Item)).scalars().all()
        for item in items:
            evidence = item.description if trusted.get(item.site_id, True) else None
            derived = classify.enrich(
                item.title,
                item.description,
                item.current_price,
                caliber=item.caliber,
                category=item.category,
                trust_description=trusted.get(item.site_id, True),
            )
            # The caliber first: it is one of the things that names a maker,
            # since a great many surplus cartridges are called after the firm
            # that designed them.
            caliber = item.caliber or derived["caliber"]
            maker = item.manufacturer or manufacturers.extract(
                session, item.title, evidence, caliber
            )
            # Only the blanks: a value the vendor stated is theirs, and this
            # command must be safe to run against a catalog that has some.
            filled = {
                "caliber": caliber,
                "country": item.country or derived["country"],
                "condition": item.condition or derived["condition"],
                "manufacturer": maker,
            }
            if (
                item.is_rifle != derived["is_rifle"]
                or item.is_pistol != derived["is_pistol"]
                or any(getattr(item, name) != value for name, value in filled.items())
            ):
                item.is_rifle = derived["is_rifle"]
                item.is_pistol = derived["is_pistol"]
                for name, value in filled.items():
                    setattr(item, name, value)
                changed += 1
        session.commit()

        rifles = session.execute(
            select(func.count(Item.id)).where(Item.is_rifle.is_(True))
        ).scalar_one()
        pistols = session.execute(
            select(func.count(Item.id)).where(Item.is_pistol.is_(True))
        ).scalar_one()

    print(f"Reclassified {changed} of {len(items)} listing(s).")
    print(f"  rifles: {rifles}   handguns: {pistols}   other: {len(items) - rifles - pistols}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """Take a database snapshot now, and prune the old ones.

    The scheduler does this daily in production. This is for taking one before
    something risky by hand.
    """
    config = get_config()
    directory = config.backups.directory
    if config.is_dev and not args.force:
        print("Backups are off in development: the database here is a scratch copy.")
        print("Re-run with --force to take one anyway.")
        return 0

    destination = backup_service.take(config)
    removed = backup_service.prune(directory, config.backups.keep)
    size = destination.stat().st_size / 1_048_576
    print(f"Wrote {destination} ({size:.1f} MB).")
    if removed:
        print(f"Pruned {len(removed)} snapshot(s) beyond the newest {config.backups.keep}.")
    kept = backup_service.existing(directory)
    print(f"{len(kept)} snapshot(s) in {directory}.")
    return 0


def cmd_infer(args: argparse.Namespace) -> int:
    """Fill blank caliber/country/maker from better-described listings.

    A vendor who publishes a scanned flyer gives us a line of OCR and nothing
    else. Another vendor selling the same rifle gives us a paragraph with every
    field parsed. This carries the second one's facts onto the first where the
    distinctive words agree; see :mod:`app.services.crosscatalog` for what
    stops that being reckless.

    Nothing is overwritten, so this is safe to run repeatedly and finds less
    each time. On a two-vendor catalog it will often find nothing at all.
    """
    with session_scope() as session:
        agreed = crosscatalog.makers_by_caliber(session)
        if agreed:
            print("Calibers the catalog agrees name one maker:")
            for caliber, maker in sorted(agreed.items()):
                print(f"  {caliber:<22} {maker}")
            print()
        filled = crosscatalog.fill_makers_from_caliber(session)
        filled += crosscatalog.fill_gaps(session, same_site=bool(args.same_site))
        for entry in sorted(filled, key=lambda f: -f.score):
            print(f"  {entry.title[:40]:<40} {entry.field}={entry.value}")
            print(f"  {'':<40} from {entry.source_title[:44]} ({entry.score})")
        session.commit()

    if not filled:
        print("Nothing to fill: no listing matched another well enough.")
        return 0
    fields = ", ".join(
        f"{name}: {sum(1 for entry in filled if entry.field == name)}"
        for name in crosscatalog.BORROWABLE
        if any(entry.field == name for entry in filled)
    )
    print(f"\nFilled {len(filled)} field(s) across the catalog ({fields}).")
    return 0


def cmd_running_scans(args: argparse.Namespace) -> int:
    """Report scans that are in flight. Exit 1 when there are any.

    Exists so `make stop` can say what it is about to interrupt. A Royal Tiger
    scan is a quarter of an hour of somebody else's bandwidth; stopping the app
    through it should be a decision, not a surprise.
    """
    with session_scope() as session:
        runs = (
            session.execute(
                select(ScanRun, Site)
                .join(Site, Site.id == ScanRun.site_id)
                .where(ScanRun.status == ScanStatus.RUNNING)
                .order_by(ScanRun.started_at)
            )
            .tuples()
            .all()
        )
        if not runs:
            if not args.quiet:
                print("No scans are running.")
            return 0

        now = utcnow()
        for run, site in runs:
            minutes = max(0, int((now - run.started_at.replace(tzinfo=UTC)).total_seconds() // 60))
            last = (run.log or "").strip().splitlines()
            detail = f" — {last[-1].strip()}" if last else ""
            print(f"  {site.name}: running for {minutes} minute(s){detail}")
        return 1


def cmd_prune_images(_args: argparse.Namespace) -> int:
    """Delete image files no listing points at.

    Both columns, not just one. A photo row names two files — the original and
    its thumbnail — and collecting only `filename` made every thumbnail in the
    store look orphaned. A prune then deleted all 1,526 of them, leaving the
    originals they were derived from in place and the browse grid with nothing
    to show. `rebuild-thumbnails` puts them back.
    """
    config = get_config()
    store = ImageStore(config)
    with session_scope() as session:
        known: set[str] = set()
        for column in (ItemPhoto.filename, ItemPhoto.thumb_filename):
            known.update(
                name
                for name in session.execute(select(column).where(column.is_not(None)))
                .scalars()
                .all()
                if name
            )
    before = store.usage_bytes()
    removed = store.prune_orphans(known)
    after = store.usage_bytes()
    print(f"Removed {removed} orphaned file(s); reclaimed {(before - after) / 1e6:.1f} MB.")
    return 0


def cmd_rebuild_thumbnails(args: argparse.Namespace) -> int:
    """Regenerate thumbnails from the originals already on disk.

    No network: a thumbnail is derived from a file we already hold, so losing
    one is not a reason to ask a vendor for the picture again.
    """
    config = get_config()
    store = ImageStore(config)
    rebuilt = failed = 0

    with session_scope() as session:
        photos = (
            session.execute(select(ItemPhoto).where(ItemPhoto.filename.is_not(None)))
            .scalars()
            .all()
        )
        for photo in photos:
            if not photo.filename:
                continue
            if not args.all and store.exists(photo.thumb_filename):
                continue
            if not store.exists(photo.filename):
                failed += 1
                continue
            target = photo.thumb_filename or f"{photo.filename.rsplit('.', 1)[0]}_t.jpg"
            made = store.write_thumbnail(photo.filename, target)
            if made is None:
                failed += 1
                continue
            photo.thumb_filename = made.relative
            photo.thumb_bytes = photo.bytes if made.relative == photo.filename else made.size
            photo.width, photo.height = made.width, made.height
            rebuilt += 1
        session.commit()

    print(f"Rebuilt {rebuilt} thumbnail(s) from {len(photos)} stored photo(s).")
    if failed:
        print(f"  {failed} could not be rebuilt: the original is missing or unreadable.")
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
    secrets_cmd = sub.add_parser(
        "secrets", help="Generate security secrets and write them into the config file."
    )
    secrets_cmd.add_argument(
        "--force",
        action="store_true",
        help="Overwrite secrets that are already set. Destructive: see the warning it prints.",
    )
    secrets_cmd.set_defaults(func=cmd_secrets)
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

    sub.add_parser(
        "reclassify", help="Re-derive rifle/handgun from stored text (no network)."
    ).set_defaults(func=cmd_reclassify)

    backup_cmd = sub.add_parser("backup", help="Snapshot the database now and prune old ones.")
    backup_cmd.add_argument(
        "--force", action="store_true", help="Take one even in development mode."
    )
    backup_cmd.set_defaults(func=cmd_backup)

    infer = sub.add_parser(
        "infer", help="Fill blank caliber/country/maker from other vendors' listings."
    )
    infer.add_argument(
        "--same-site",
        action="store_true",
        help="Also borrow from the same vendor (off by default: a vendor who "
        "leaves a field blank on one listing tends to leave it blank on the next).",
    )
    infer.set_defaults(func=cmd_infer)

    photos = sub.add_parser("fetch-photos", help="Download queued photos without re-scraping.")
    photos.add_argument("--site", help="Limit to one site slug.")
    photos.add_argument(
        "--limit", type=int, help="Stop after this many (default: the per-scan budget)."
    )
    photos.set_defaults(func=cmd_fetch_photos)

    running = sub.add_parser("running-scans", help="List in-flight scans; exit 1 if there are any.")
    running.add_argument(
        "--quiet", action="store_true", help="Print nothing when no scan is running."
    )
    running.set_defaults(func=cmd_running_scans)

    thumbs = sub.add_parser(
        "rebuild-thumbnails", help="Regenerate missing thumbnails from stored originals."
    )
    thumbs.add_argument(
        "--all", action="store_true", help="Rebuild every thumbnail, not only the missing ones."
    )
    thumbs.set_defaults(func=cmd_rebuild_thumbnails)

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
