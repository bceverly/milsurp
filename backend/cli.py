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
milsurp refetch-details          re-read product pages on the next scan
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
    as_utc,
    utcnow,
)
from app.scrapers.base import is_prose
from app.security import (
    PasswordPolicyError,
    hash_password,
    validate_password,
)
from app.services import (
    armory,
    bootstrap,
    classify,
    crosscatalog,
    discovery,
    manufacturers,
    scan_service,
)
from app.services import backup as backup_service
from app.services import digest as digest_service
from app.services.image_store import ImageStore


def _fmt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "never"


def cmd_init(_args: argparse.Namespace) -> int:
    config = get_config()
    print(f"Mode:      {config.mode}")
    print(f"Config:    {config.source_path or 'built-in defaults (no file found)'}")
    print(f"Database:  {config.database.describe()}")
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
    # Everything printed below is taken from _SECRET_SETTINGS, which is a
    # literal in this file. The config text is read to decide *whether* to
    # print, never to decide *what*: it holds the secrets, and a name recovered
    # from it is a name that came out of a file full of them.
    already_set = {name for name, _cost in _SECRET_SETTINGS if _is_set(text, name)}
    if already_set and not args.force:
        names = [name for name, _cost in _SECRET_SETTINGS if name in already_set]
        print(f"{path} already has: {', '.join(names)}.", file=sys.stderr)
        print("Rotating them is destructive:", file=sys.stderr)
        for name, cost in _SECRET_SETTINGS:
            print(f"  {name}: {cost}", file=sys.stderr)
        print("Re-run with --force if that is what you want.", file=sys.stderr)
        return 1

    written: set[str] = set()
    for name, _cost in _SECRET_SETTINGS:
        text, count = re.subn(
            _SETTING_LINE.format(name=name),
            lambda match: f'{match.group(1)}"{generate_secret()}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if not count:
            print(f"Could not find a '{name}:' line in {path}.", file=sys.stderr)
            return 1
        written.add(name)

    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)

    wrote = [name for name, _cost in _SECRET_SETTINGS if name in written]
    print(f"Wrote {', '.join(wrote)} to {path} (mode 600).")
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
        site_slug=args.site,
        limit=args.limit,
        progress=lambda message: print(f"  {message}"),
        retry_failed=args.retry_failed,
    )
    if not downloaded:
        print("No photos are waiting to be downloaded.")
    else:
        print(f"Downloaded {downloaded} photo(s).")
    return 0


def cmd_resting(args: argparse.Namespace) -> int:
    """Show, or lift, the hosts every fetcher is currently leaving alone."""
    from app.services import cooldown

    if args.clear is not None:
        lifted = cooldown.clear(args.clear or None)
        target = args.clear or "every host"
        print(f"Lifted {lifted} pause(s) on {target}.")
        return 0

    rows = cooldown.active()
    if not rows:
        print("No hosts are being rested; everything is fetchable.")
        return 0

    now = utcnow()
    print(f"{'HOST':<34} {'FOR':>8}  {'TIMES':>5}  REASON")
    for row in rows:
        remaining = (as_utc(row.until) - now).total_seconds()
        print(
            f"{row.host[:34]:<34} {_duration(remaining):>8}  {row.refusals:>5}  {row.reason or '—'}"
        )
    print("\nRun 'cli.py resting --clear' to lift these once the cause is fixed.")
    return 0


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def cmd_reclassify(args: argparse.Namespace) -> int:
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
                # Under --recompute the stored caliber is withheld here too.
                # enrich() hands back whatever it is given, so passing the
                # stale value in made every downstream step vouch for it and
                # the flag changed nothing at all.
                caliber=None if args.recompute else item.caliber,
                category=item.category,
                trust_description=trusted.get(item.site_id, True),
            )
            # The caliber first: it is one of the things that names a maker,
            # since a great many surplus cartridges are called after the firm
            # that designed them.
            #
            # "First" has to include the armory's normalization of it, and did
            # not at the outset: the maker lookup saw the raw spelling, the
            # armory tidied it afterwards, and the *next* run found a maker
            # the first had missed. That made the command need two passes to
            # settle, which is a bad property for something whose whole job is
            # to say what changed.
            # Under --recompute the stored caliber is deliberately NOT handed
            # to the armory. fill_in() normalizes what it is given and hands it
            # straight back, so passing the stale value in made the armory
            # vouch for it and --recompute changed nothing at all.
            stated = derived["caliber"] if args.recompute else item.caliber
            found = armory.fill_in(session, item.title, evidence, stated)
            caliber = found.caliber or stated or derived["caliber"]
            maker = (
                manufacturers.extract(session, item.title, evidence, caliber)
                if args.recompute
                else item.manufacturer
                or manufacturers.extract(session, item.title, evidence, caliber)
            )
            # Only the blanks by default: a value the vendor stated is theirs,
            # and this command must be safe to run against a catalog that has
            # some.
            #
            # --recompute overrides that, and exists because the default has a
            # cost that took a while to notice: most stored calibers were
            # derived here rather than stated by a vendor, and nothing records
            # which. So a fix to the caliber rules never reached the listings
            # that needed it -- ".38 Super" stayed filed as ".38 Special" long
            # after the rule that did it was corrected, because the wrong
            # answer looked like something to preserve.
            if args.recompute:
                filled = {
                    "caliber": caliber or item.caliber,
                    # The title first, then the armory. A listing that names a
                    # country is talking about the gun in front of them; the
                    # model is talking about where the pattern comes from, and
                    # it answers the far commoner case of a title that names
                    # no country at all.
                    "country": derived["country"] or found.country or item.country,
                    "condition": derived["condition"] or item.condition,
                    "manufacturer": manufacturers.canonical(session, found.manufacturer or maker),
                }
            else:
                filled = {
                    "caliber": caliber,
                    "country": item.country or derived["country"] or found.country,
                    "condition": item.condition or derived["condition"],
                    "manufacturer": manufacturers.canonical(session, maker or found.manufacturer),
                }
            flags = {
                "firearm_model_id": found.model_id,
                "is_rifle": derived["is_rifle"],
                "is_pistol": derived["is_pistol"],
                "is_bayonet": derived["is_bayonet"],
                "is_parts_kit": derived["is_parts_kit"],
            }
            # Refines, never promotes -- see _apply_catalog in scan_service
            # for why. A model an admin has vouched for says which of the two
            # buckets a firearm belongs in better than the words can; it does
            # not say whether this listing is selling a firearm at all.
            if found.kind is not None and (flags["is_rifle"] or flags["is_pistol"]):
                flags["is_rifle"] = found.kind.is_long_gun
                flags["is_pistol"] = found.kind.is_handgun
            if any(getattr(item, name) != value for name, value in (flags | filled).items()):
                for name, value in flags.items():
                    setattr(item, name, value)
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
        bayonets = session.execute(
            select(func.count(Item.id)).where(Item.is_bayonet.is_(True))
        ).scalar_one()
        kits = session.execute(
            select(func.count(Item.id)).where(Item.is_parts_kit.is_(True))
        ).scalar_one()
        # "Other" as the browse page defines it: what none of the four claim.
        #
        # Not "everything that is not a rifle or a handgun", which is what this
        # counted before and which quietly included the bayonets and parts kits
        # printed on the next line. It read 131 against a filter showing 88,
        # and the number here is what somebody checks their work against.
        other = session.execute(
            select(func.count(Item.id)).where(
                Item.is_rifle.is_(False),
                Item.is_pistol.is_(False),
                Item.is_bayonet.is_(False),
                Item.is_parts_kit.is_(False),
            )
        ).scalar_one()

    print(f"Reclassified {changed} of {len(items)} listing(s).")
    print(f"  rifles: {rifles}   handguns: {pistols}   other: {other}")
    print(f"  bayonets: {bayonets}   parts kits: {kits}")
    return 0


def cmd_armory(args: argparse.Namespace) -> int:
    """Seed, export and sync the armory of models and calibers.

    The armory is knowledge rather than state: which cartridges are the same
    round written differently, which firms built which model, what kind of gun
    a designation names. It is worth version control, and these three commands
    are how it gets there and back.

      seed      add anything the shipped file has and this database does not.
                Additive only, everything arrives awaiting approval.
      export    write this database's armory to a file fit to commit.
      sync      reconcile this database with such a file. Prints a plan and
                does nothing unless --apply is given.
      discover  read every stored listing and write down the cartridges, firms
                and designations the armory cannot explain, as pending rows.
                Every scan now does this for the listings it touched; this is
                the one-off pass over a catalog collected before it did.
    """
    action = args.armory_command
    simple = {"seed": _armory_seed, "discover": _armory_discover, "export": None}
    if action == "export":
        path = Path(args.file)
        with session_scope() as session:
            written = armory.write_export(session, path)
        print(f"Wrote {written} row(s) to {path}.")
        return 0
    if action in simple:
        return simple[action]()

    path = Path(args.file)
    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 1
    with session_scope() as session:
        plan = armory.plan_sync(session, path)
        if not plan:
            print(f"Nothing to do; {path} matches this database.")
            return 0
        _print_plan(plan, prune=args.prune)
        if not args.apply:
            print("\nNothing changed. Re-run with --apply to carry it out.")
            return 0
        done = armory.apply_sync(session, path, prune=args.prune)
    print(
        f"\nApplied: {done['added']} added, {done['updated']} updated, {done['deleted']} deleted."
    )
    return 0


def _print_plan(plan, prune: bool) -> None:
    """Show every change before any of it happens.

    Deletions are listed even when --prune is off, marked as skipped. A plan
    that hides what it is not going to do is how somebody discovers the flag
    by losing rows to it later.
    """
    for title, changes in (
        ("Manufacturers", plan.manufacturers),
        ("Calibers", plan.calibers),
        ("Models", plan.models),
    ):
        if not changes:
            continue
        print(f"\n{title}:")
        for change in changes:
            if change.action == "delete" and not prune:
                print(f"  skip    {change.name}  (in the database, not in the file; --prune)")
            elif change.action == "update":
                print(f"  update  {change.name}  ({', '.join(change.fields)})")
            else:
                print(f"  {change.action:7} {change.name}")
    counted = plan.counted()
    skipped = " (skipped without --prune)" if counted["delete"] and not prune else ""
    print(
        f"\n{counted['add']} to add, {counted['update']} to update, "
        f"{counted['delete']} to delete{skipped}."
    )


def cmd_backup(args: argparse.Namespace) -> int:
    """Take a database snapshot now, and prune the old ones.

    The scheduler does this daily in production. This is for taking one before
    something risky by hand.
    """
    config = get_config()
    directory = config.backups.directory
    with session_scope() as session:
        settings = backup_service.settings(session)
        if not settings.enabled and not args.force:
            print("The backup schedule is switched off (Backups, in the admin navigation).")
            print("Re-run with --force to take one anyway.")
            return 0

        # force=True either way: reaching here means the schedule is on, or the
        # person said --force. Both are a decision to take one now.
        destination = backup_service.run(session, config, force=True)
        keep = settings.keep

    if destination is None:  # pragma: no cover - force makes this unreachable
        return 0
    size = destination.stat().st_size / 1_048_576
    print(f"Wrote {destination} ({size:.1f} MB).")
    kept = backup_service.existing(directory)
    print(f"{len(kept)} snapshot(s) in {directory} (keeping the newest {keep}).")
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


def cmd_refetch_details(args: argparse.Namespace) -> int:
    """Mark listings for a fresh product-page read on the next scan.

    A scan skips the product page of any listing it has already fetched one
    for, which is what keeps a re-scan cheap -- and what means a fix to how a
    page is *read* never reaches the listings that were read wrongly. This
    clears that mark so the next scan of the site fetches them again.

    The default picks the listings whose stored description is not prose --
    ``scrapers.base.is_prose``, the same test the scrapers now apply before
    keeping one. That is the case this was written for: 85 Apex Gun Parts
    listings whose description was a Magento Page Builder stylesheet.
    ``--site`` takes a whole site instead, and ``--all`` every listing that
    has ever been fetched.
    """
    with session_scope() as session:
        query = select(Item).where(Item.detail_fetched_at.is_not(None))
        if args.site:
            site = session.execute(select(Site).where(Site.slug == args.site)).scalar_one_or_none()
            if site is None:
                print(f"No site with slug '{args.site}'.", file=sys.stderr)
                return 1
            query = query.where(Item.site_id == site.id)

        items = list(session.execute(query).scalars())
        if not (args.all or args.site):
            # It has to *have* a description that is not prose. is_prose()
            # answers "is this text worth keeping", so it says False for an
            # empty one too -- and a listing whose product page simply carries
            # no description is not damaged and must not be re-fetched.
            items = [i for i in items if i.description and not is_prose(i.description)]

        by_site: dict[int, int] = {}
        for item in items:
            # A dry run counts and does not touch, not even in memory: the
            # caller asked what would happen, and a half-applied change in a
            # live session is not that.
            if not args.dry_run:
                item.detail_fetched_at = None
            by_site[item.site_id] = by_site.get(item.site_id, 0) + 1
        if not args.dry_run:
            session.commit()

        slugs = {
            site.id: site.slug
            for site in session.execute(select(Site).where(Site.id.in_(by_site))).scalars()
        }

    verb = "Would clear" if args.dry_run else "Cleared"
    print(f"{verb} the detail mark on {len(items)} listing(s).")
    for site_id, count in sorted(by_site.items(), key=lambda pair: -pair[1]):
        print(f"  {count:6d}  {slugs.get(site_id, site_id)}")
    if items and not args.dry_run:
        print("Their product pages are read again on the next scan of each site.")
    return 0


def _add_refetch_details_command(sub) -> None:
    command = sub.add_parser(
        "refetch-details",
        help="Re-read product pages on the next scan (default: listings whose "
        "stored description is markup rather than prose).",
    )
    command.add_argument("--site", help="Only this site's listings, whatever their description.")
    command.add_argument(
        "--all",
        action="store_true",
        help="Every listing that has ever had its product page fetched.",
    )
    command.add_argument(
        "--dry-run", action="store_true", help="Report what would be cleared and change nothing."
    )
    command.set_defaults(func=cmd_refetch_details)


def _add_reclassify_command(sub) -> None:
    """The reclassify subcommand, kept out of build_parser() for its own sake."""
    command = sub.add_parser(
        "reclassify", help="Re-derive rifle/handgun from stored text (no network)."
    )
    command.add_argument(
        "--recompute",
        action="store_true",
        help="Also correct caliber, country, condition and maker that are already "
        "set, rather than only filling blanks. Use after changing the rules: most "
        "stored values were derived here, not stated by a vendor, so a fix "
        "otherwise never reaches the listings that need it. A vendor-supplied "
        "value comes back on the next scan of that site.",
    )
    command.set_defaults(func=cmd_reclassify)


def _armory_seed() -> int:
    """Add what the shipped file has and this database does not."""
    with session_scope() as session:
        report = armory.seed(session)
    print(
        f"Added {report.manufacturers} manufacturer(s), {report.calibers} caliber(s) "
        f"and {report.models} model(s), all awaiting approval."
    )
    return 0


def _armory_discover() -> int:
    """The one-off pass: propose armory rows from every listing already stored.

    A scan does this for the listings it touched, so this exists for a catalog
    collected before that did -- and for a rules change, since a tightened
    extractor should be re-run over everything rather than only over whatever
    is scraped next.
    """
    with session_scope() as session:
        items = session.execute(select(Item)).scalars().all()
        found = discovery.discover(session, items)
        session.commit()
    print(f"Read {len(items)} listing(s); proposed {found.summary()}, awaiting approval.")
    if found.manufacturers:
        print("\n  Manufacturers proposed:")
        for name in sorted(found.manufacturers):
            print(f"    {name}")
    print("\n  Nothing proposed decides anything until somebody promotes it, at /armory.")
    return 0


def _add_armory_commands(sub) -> None:
    """The armory subcommands, kept out of build_parser() for its own sake."""
    armory_cmd = sub.add_parser(
        "armory", help="Seed, export or sync the model and caliber reference tables."
    )
    armory_sub = armory_cmd.add_subparsers(dest="armory_command", required=True)
    armory_sub.add_parser(
        "seed", help="Add what the shipped armory file has and this database does not."
    )
    armory_sub.add_parser(
        "discover",
        help="Propose armory rows from every stored listing (scans do this "
        "for their own listings automatically).",
    )
    armory_export = armory_sub.add_parser(
        "export", help="Write this database's armory to a file fit to commit."
    )
    armory_export.add_argument(
        "--file",
        default=str(armory.SEED_FILE),
        help="Where to write it. Defaults to the shipped armory file in this "
        "repository, so the change is a reviewable diff.",
    )
    armory_sync = armory_sub.add_parser(
        "sync", help="Reconcile this database with an armory file. Prints a plan first."
    )
    armory_sync.add_argument(
        "--file",
        default=str(armory.SEED_FILE),
        help="The file to read (default: the shipped armory file in this repository).",
    )
    armory_sync.add_argument(
        "--apply", action="store_true", help="Carry the plan out instead of just printing it."
    )
    armory_sync.add_argument(
        "--prune",
        action="store_true",
        help="Also delete rows the file does not list. Off by default: the "
        "armory is curated in two places and a row missing from the file is "
        "more often unexported than unwanted.",
    )
    armory_cmd.set_defaults(func=cmd_armory)


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

    _add_reclassify_command(sub)
    _add_refetch_details_command(sub)

    _add_armory_commands(sub)

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
    photos.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also try photos that have been given up on after repeated failures.",
    )
    photos.set_defaults(func=cmd_fetch_photos)

    resting = sub.add_parser("resting", help="Show hosts being left alone after refusing requests.")
    resting.add_argument(
        "--clear",
        metavar="HOST",
        nargs="?",
        const="",
        help="Lift the pause on one host, or on all of them when given no value.",
    )
    resting.set_defaults(func=cmd_resting)

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
