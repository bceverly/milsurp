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
milsurp canary                   check every shop still answers and still parses
milsurp catch-up                 re-apply this version's rules to stored rows
milsurp prune-images             delete image files no listing references
milsurp refetch-details          re-read product pages on the next scan
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any

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
from app.security import (
    PasswordPolicyError,
    hash_password,
    validate_password,
)
from app.services import (
    armory,
    bootstrap,
    canary,
    classify,
    crosscatalog,
    discovery,
    mailer,
    manufacturers,
    provenance,
    scan_service,
    twofactor,
    webpush,
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
    # The VAPID pair is generated together and written as two settings, because
    # that is how the file holds it. Only the private half is a secret; the
    # public one is handed to every browser that subscribes. They are listed
    # together anyway: they are useless apart, and regenerating one without the
    # other is the mismatch that reads like a network fault.
    ("vapid_private_key", "every push subscription stops working"),
    ("vapid_public_key", "every push subscription stops working"),
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


#: The block every secret belongs to. Anchoring on it rather than on a sibling
#: setting means the insert still works in a file where the neighbours have been
#: reordered, which is a thing people do to their own config.
_SECURITY_BLOCK = re.compile(r"^(\s*)security:\s*$", re.MULTILINE)


def _insert_setting(text: str, name: str, value: str) -> tuple[str, int]:
    """Add `name: "value"` to the security block. (text, 1) or (text, 0).

    Placed at the top of the block rather than the bottom: the bottom of a YAML
    block is wherever the indentation stops, which is a harder thing to find
    correctly than the line after the header, and getting it wrong writes the
    setting into whatever section came next.
    """
    match = _SECURITY_BLOCK.search(text)
    if match is None:
        return text, 0
    indent = match.group(1) + "  "
    line = f'{indent}{name}: "{value}"\n'
    at = match.end() + 1
    return text[:at] + line + text[at:], 1


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

    # The VAPID halves are one key, so they are generated once and written to
    # the two settings that hold them. Generating each independently would
    # produce a public key that does not belong to the private one, which is
    # the mismatch that reads like a network fault at the far end.
    vapid_private, vapid_public = webpush.generate_keys()
    values = {"vapid_private_key": vapid_private, "vapid_public_key": vapid_public}

    written: set[str] = set()
    for name, _cost in _SECRET_SETTINGS:
        text, count = re.subn(
            _SETTING_LINE.format(name=name),
            lambda match, name=name: f'{match.group(1)}"{values.get(name) or generate_secret()}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if not count:
            # A setting added in a later release is simply not in a config file
            # written by an earlier one, and every upgraded installation has
            # one of those. Adding the line is the whole fix; refusing is how
            # `milsurp secrets` would have failed on every machine that already
            # had a config, which is all of them.
            text, count = _insert_setting(text, name, values.get(name) or generate_secret())
        if not count:
            # _insert_setting only fails one way: there is no `security:`
            # block to put the line in. So say that, rather than naming the
            # setting -- "could not find a 'jwt_secret:' line" sent people
            # looking for a line that is *supposed* to be missing on an
            # upgraded config, when what is actually absent is the block.
            #
            # It also keeps the names of these settings out of the output
            # entirely. They are not secrets -- the values are, and those are
            # never printed, which is the whole design of this command -- but
            # a scanner cannot tell `"password_pepper"` the identifier from
            # `"password_pepper"` the credential, and it was right to ask.
            print(
                f"{path} has no 'security:' block to write these into. Add one "
                f"(see config.yaml.sample) and run this again.",
                file=sys.stderr,
            )
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


def cmd_twofactor(args: argparse.Namespace) -> int:
    """Show or switch off two-factor for one account.

    **The way back in when the phone and the recovery codes are both gone.**
    Every other route deliberately requires something the locked-out person no
    longer has, which is what makes a second factor worth having -- so the last
    resort is shell access to the machine, and that is this.

    Deliberately not a way to *turn it on*: enrollment needs a secret shown to
    the person holding the phone, which a terminal on the server is not.
    """
    with session_scope() as session:
        user = session.execute(select(User).where(User.username == args.username)).scalars().first()
        if user is None:
            print(f"No account named {args.username!r}.", file=sys.stderr)
            return 1

        if not args.disable:
            if twofactor.is_enabled(user):
                left = twofactor.recovery_codes_left(session, user)
                when = _fmt(user.totp_confirmed_at)
                print(f"{user.username}: two-factor ON since {when}, {left} recovery code(s) left.")
            else:
                print(f"{user.username}: two-factor is off.")
            return 0

        if not twofactor.is_enabled(user) and not user.totp_secret:
            print(f"{user.username}: two-factor is already off; nothing to do.")
            return 0

        twofactor.disable(session, user)
        # Every token already issued stops working. Somebody who has lost
        # control of a phone may have lost control of a session with it, and
        # leaving those alive would make this a smaller fix than it looks.
        user.token_version += 1
        session.commit()
        print(f"{user.username}: two-factor is off and every existing session is signed out.")
        print("Sign in with the password alone, then turn it back on from Settings.")
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

    rows = cooldown.tracked()
    if not rows:
        print("No hosts are being rested; everything is fetchable.")
        return 0

    # Two columns because there are two states. PAUSED is "do not ask at all,
    # for this long". PACE is "ask, but leave this much between requests" --
    # which is what a host gets while it works its refusals back down to zero,
    # and what used to be invisible because only the pause was recorded.
    now = utcnow()
    print(f"{'HOST':<34} {'PAUSED':>8} {'PACE':>6}  {'TIMES':>5}  REASON")
    for row in rows:
        remaining = max(0.0, (as_utc(row.until) - now).total_seconds())
        pace = cooldown.pace_after(row.refusals)
        print(
            f"{row.host[:34]:<34} {_duration(remaining) if remaining else '—':>8} "
            f"{f'{pace:.0f}s' if pace else '—':>6}  {row.refusals:>5}  {row.reason or '—'}"
        )
    print("\nRun 'cli.py resting --clear' to lift these once the cause is fixed.")
    return 0


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


#: What --recompute is able to overwrite, and therefore what --fields may name.
#: Not the flags: rifle/handgun and its siblings are derived from the text every
#: time and have no vendor-supplied version to protect.
RECOMPUTABLE = ("caliber", "country", "condition", "manufacturer")


def _permitted(
    item: Item,
    filled: dict[str, Any],
    wanted: set[str],
    protected: dict[str, int],
) -> dict[str, Any]:
    """Cut a rebuild down to the fields it is allowed to overwrite.

    Two gates, and they answer different questions. ``--fields`` is the
    operator saying which fields this fix is about; a field left out keeps the
    fill-blanks-only behavior, so a caliber fix need not cost every listing its
    maker. **Provenance is the row saying whose value it is** -- the vendor
    published it, or nobody recorded who did, and neither is ours to rewrite.

    Without that second gate the flag could not tell a correction from a
    demolition. Scoped to nothing but the caliber it changed 3,187 of 11,038
    listings, 2,251 of them to nothing at all, because it discards the stored
    value by design and re-derives from the title. A Carl Gustafs 1896 stated
    as 6.5x55mm Swedish came back 8mm Mauser.

    Counts what it refused, into *protected*, so a run that reached almost
    nothing says so rather than reporting a quiet success.

    A field it *does* rebuild is stamped ``derived`` on the way past -- even
    when the value it lands on is the one already there. A row whose answer the
    rules would have produced anyway is a row the rules own, and recording that
    is what lets the next fix reach it; without it the unknown rows stay
    unknown forever and this earns nothing beyond what a scan rewrites.
    """
    allowed: dict[str, Any] = {}
    for name, value in filled.items():
        if name not in wanted:
            allowed[name] = getattr(item, name) or value
        elif provenance.may_recompute(item, name):
            allowed[name] = value
            setattr(item, provenance.SOURCE_COLUMNS[name], provenance.DERIVED)
        else:
            allowed[name] = getattr(item, name)
            protected[name] = protected.get(name, 0) + 1
    return allowed


def cmd_reclassify(args: argparse.Namespace) -> int:
    """Re-derive rifle/pistol and the other inferred fields from stored text.

    Classification runs on every upsert, so a re-scan fixes it — but a re-scan
    of a large catalog is a quarter of an hour of somebody else's bandwidth for
    a change that needs no network at all. This re-runs the heuristics over
    what is already in the database.
    """
    wanted = {name.strip().lower() for name in (args.fields or "").split(",") if name.strip()}
    unknown = wanted - set(RECOMPUTABLE)
    if unknown:
        print(
            f"Unknown field(s): {', '.join(sorted(unknown))}. Valid: {', '.join(RECOMPUTABLE)}.",
            file=sys.stderr,
        )
        return 1

    changed = 0
    #: field -> how many listings declined the rebuild because the value was
    #: the vendor's, or of unknown origin. Reported at the end: a run that
    #: skipped most of the catalog has not failed, but somebody expecting a
    #: rule fix to land needs to know it did not reach these.
    protected: dict[str, int] = {}
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
                # Not optional. The whole reason stated_kind is a column and
                # not something worked out during a scan is that reclassify
                # rebuilds from the row -- and leaving it out here threw the
                # vendor's own answer away on every run.
                stated_kind=item.stated_kind,
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
            found = armory.fill_in(
                session,
                item.title,
                evidence,
                stated,
                stated_kind=item.stated_kind,
                # See fill_in: a bayonet naming the model it fits must not take
                # that model's caliber, maker or country.
                is_firearm=derived["is_rifle"] or derived["is_pistol"],
            )
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
            # Settled before the country, because the last thing asked about
            # the country is where *this firm* is. _apply_catalog does the
            # same in the same order; the two are separate code paths over one
            # decision, and every field either forgets has to be found by
            # noticing it is missing. is_police_surplus was added to one and
            # not the other once already.
            if args.recompute:
                chosen_maker = manufacturers.canonical(session, found.manufacturer or maker)
            else:
                chosen_maker = manufacturers.canonical(session, maker or found.manufacturer)
            from_maker = manufacturers.country_for(session, chosen_maker)

            if args.recompute:
                # No "or item.<field>" on any of these, which is the whole
                # point of the flag: --recompute must be able to *clear* a
                # value and not only change one. A bayonet that took ".32 ACP"
                # from the Beretta M1935 it fits has no caliber at all now, and
                # with the old fallback the wrong answer was the one thing the
                # rebuild could never reach. The fields nobody named are still
                # protected -- see the --fields filter below, which puts the
                # stored value back for every field outside `wanted`.
                filled = {
                    "caliber": caliber,
                    # The title first, then the armory, then the firm. A
                    # listing that names a country is talking about the gun in
                    # front of them; the model is talking about where the
                    # pattern comes from, and it answers the far commoner case
                    # of a title that names no country at all. The maker is a
                    # proxy for the model's answer and goes last.
                    "country": derived["country"] or found.country or from_maker,
                    "condition": derived["condition"],
                    "manufacturer": chosen_maker,
                }
            else:
                filled = {
                    "caliber": caliber,
                    "country": item.country or derived["country"] or found.country or from_maker,
                    "condition": item.condition or derived["condition"],
                    "manufacturer": chosen_maker,
                }
            flags = {
                "firearm_model_id": found.model_id,
                "is_rifle": derived["is_rifle"],
                "is_pistol": derived["is_pistol"],
                "is_bayonet": derived["is_bayonet"],
                "is_parts_kit": derived["is_parts_kit"],
                "is_police_surplus": derived["is_police_surplus"],
            }
            # Refines, never promotes -- see _apply_catalog in scan_service
            # for why. A model an admin has vouched for says which of the two
            # buckets a firearm belongs in better than the words can; it does
            # not say whether this listing is selling a firearm at all.
            if found.kind is not None and (flags["is_rifle"] or flags["is_pistol"]):
                flags["is_rifle"] = found.kind.is_long_gun
                flags["is_pistol"] = found.kind.is_handgun
            # The finer kind, rebuilt here as it is during a scan. Only on a
            # firearm: a bayonet has no form. See Item.kind.
            flags["kind"] = (
                classify.finer_kind(
                    found.kind,
                    item.stated_kind,
                    classify.form_in_title(
                        item.title,
                        is_rifle=bool(flags["is_rifle"]),
                        is_pistol=bool(flags["is_pistol"]),
                    ),
                )
                if (flags["is_rifle"] or flags["is_pistol"])
                else None
            )
            # --recompute overwrites; --fields says which of them it may
            # overwrite. A field left out keeps the fill-blanks-only behavior,
            # so a caliber fix need not cost every listing its maker.
            #
            # **And provenance says which of them it is allowed to.** A value
            # the vendor published is theirs, and one of unknown origin is
            # treated the same way -- see app/services/provenance.py. Without
            # this gate the flag could not tell a correction from a
            # demolition: scoped to nothing but the caliber it changed 3,187
            # of 11,038 listings, 2,251 of them to nothing at all.
            if args.recompute:
                filled = _permitted(item, filled, wanted, protected)

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
    if protected:
        detail = ", ".join(f"{name}: {count}" for name, count in sorted(protected.items()))
        print(f"  left alone, stated by the vendor or of unknown origin — {detail}")
        print("  A row's origin is recorded by the scan that writes it, so this")
        print("  number falls as each site is scanned.")
    return 0


def _armory_qualify(args: argparse.Namespace) -> int:
    """Make a bare designation say who built it: "M44" -> "Mosin-Nagant M44".

    Only where the row already names exactly one maker, so nothing is inferred
    -- see armory.plan_qualify. The old name stays on as an alias, which is
    what makes this safe to run against a live catalog: a listing that says
    only "M44" still matches, and the row simply answers to more than it did.
    """
    with session_scope() as session:
        plan = armory.plan_qualify(session)
        if not plan:
            print("Nothing to qualify: no approved row is a bare designation with one maker.")
            return 0
        for rename in plan:
            print(f"  {rename.was:<22} -> {rename.now}")
        print(f"\n{len(plan)} row(s) would be renamed; each keeps its old name as an alias.")
        if not args.apply:
            print("Nothing changed. Re-run with --apply to carry it out.")
            return 0
        done = armory.apply_qualify(session, plan)
    print(f"Renamed {done} row(s).")
    return 0


def _armory_tidy(args: argparse.Namespace) -> int:
    """Fill a row from its own listings; switch off one that says nothing.

    The residue of approving a discovery queue wholesale: 86 approved rows with
    no kind, no country, no maker and no cartridge. Of those, 57 held no
    listing either, so they could not answer a question if one were asked --
    and the other 29 were answerable from the listings they already hold.
    """
    with session_scope() as session:
        plan = armory.plan_tidy(session)
        if not plan:
            print("Nothing to tidy: every approved row either says something or answers for one.")
            return 0
        for entry in [e for e in plan if e.action == "fill"]:
            print(f"  fill    {entry.name:<26} {entry.detail}")
        for entry in [e for e in plan if e.action == "retire"]:
            print(f"  retire  {entry.name:<26} {entry.detail}")
        fills = sum(1 for e in plan if e.action == "fill")
        retires = len(plan) - fills
        print(f"\n{fills} row(s) would be filled in, {retires} switched off.")
        if not args.apply:
            print("Nothing changed. Re-run with --apply to carry it out.")
            return 0
        filled, retired = armory.apply_tidy(session, plan)
    print(f"Filled {filled} field(s); switched off {retired} row(s).")
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
      qualify   rename rows whose name is only a designation so it names the
                firm already on them. Prints a plan and does nothing unless
                --apply is given.
      tidy      fill a row's blanks from what its own listings agree on, and
                switch off the ones that say nothing and match nothing. Also
                a plan unless --apply is given.
    """
    action = args.armory_command
    simple = {
        "seed": _armory_seed,
        "discover": _armory_discover,
        # A lambda so it joins the same dispatch as the others rather than
        # adding a seventh return to this function.
        "qualify": lambda: _armory_qualify(args),
        "tidy": lambda: _armory_tidy(args),
        "export": None,
    }
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


def cmd_catch_up(args: argparse.Namespace) -> int:
    """Bring stored rows into line with the rules this version ships.

    A release changes how text is read, and the listings already in the
    database were read by the old rules. Nothing re-reads them on its own: a
    scan only re-derives the listings it touches, so a rule fix reaches the
    shelf a vendor happens to restock and no further. Every upgrade has
    therefore needed somebody to remember a manual pass, on every machine.

    **Every step here is idempotent**, which is what lets the packaging run it
    unattended: a second run finds nothing to do and says so. That is a
    property each step has to keep, not a hope -- ``reclassify`` without
    ``--recompute`` only fills blanks, and ``armory qualify`` matches on the
    name it is about to change. A step that did something different the second
    time would turn every upgrade into a mutation.

    Ordered, and the order matters: the armory is renamed before the listings
    are re-read, so the pass that reads them sees the finished table.

    Never raises. A data pass that fails is a reason to look, not a reason to
    leave a package half-configured -- see the migration block in
    debian/milsurp.postinst for the same argument about the schema.
    """
    steps: list[tuple[str, Callable[[], int]]] = [
        ("armory names", lambda: _catch_up_qualify(args.dry_run)),
        ("listing facts", lambda: _catch_up_reclassify(args.dry_run)),
    ]
    failed = 0
    for label, run in steps:
        try:
            run()
        except Exception as exc:  # deliberate: see the docstring
            failed += 1
            print(f"  {label}: FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
    if failed:
        print(f"\n{failed} step(s) failed. The database is unchanged by those.", file=sys.stderr)
        return 1
    print("\nStored data is in line with this version's rules.")
    return 0


def _catch_up_qualify(dry_run: bool) -> int:
    with session_scope() as session:
        plan = armory.plan_qualify(session)
        if not plan:
            print("  armory names: nothing to qualify.")
            return 0
        for rename in plan:
            print(f"    {rename.was} -> {rename.now}")
        if dry_run:
            print(f"  armory names: {len(plan)} row(s) would be renamed.")
            return 0
        done = armory.apply_qualify(session, plan)
    print(f"  armory names: renamed {done} row(s).")
    return done


def _catch_up_reclassify(dry_run: bool) -> int:
    if dry_run:
        # No --dry-run on reclassify, and inventing one here would mean a
        # second implementation of the thing being checked.
        print("  listing facts: would re-derive kind, caliber, country and maker.")
        return 0
    print("  listing facts:")
    return cmd_reclassify(argparse.Namespace(recompute=False, fields=""))


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


_CANARY_MARK = {
    canary.Verdict.OK: "ok",
    canary.Verdict.REFUSED: "REFUSED",
    canary.Verdict.RESTING: "RESTING",
    canary.Verdict.EMPTY: "EMPTY",
    canary.Verdict.TIMEOUT: "TIMEOUT",
    canary.Verdict.BROKE: "BROKE",
}


def _canary_report(
    results: list[canary.Probe],
    backups: canary.BackupHealth | None = None,
    site: canary.SiteHealth | None = None,
) -> str:
    """The failures, as plain text, for a terminal and for an email body."""
    bad = canary.failures(results)
    lines = []
    if site is not None and site.unhappy:
        # Above even the backups. Every other line in this report is about
        # something that will matter later; this one is about right now, and
        # about the only thing here that visitors can see for themselves.
        lines += [f"SITE: {site.headline}", ""]
    if backups is not None and backups.stale:
        # First, because it is the one nobody else will ever mention. A vendor
        # going quiet shows up as an empty shelf eventually; a backup that
        # stopped shows up on the day it is needed.
        lines += [f"BACKUPS: {backups.headline}", ""]
    lines += [
        f"{len(bad)} of {len(results)} shops did not answer with listings.",
        "",
    ]
    for probe in bad:
        status = f" HTTP {probe.status}" if probe.status else ""
        lines.append(f"  {probe.name} ({probe.slug}) -- {probe.verdict.value}{status}")
        if probe.detail:
            lines.append(f"      {probe.detail}")
    healthy = sorted(probe.slug for probe in results if probe.healthy)
    if healthy:
        lines.append("")
        lines.append("Healthy: " + ", ".join(healthy))
    return "\n".join(lines)


def _mail_canary(
    results: list[canary.Probe],
    backups: canary.BackupHealth | None = None,
    site: canary.SiteHealth | None = None,
) -> None:
    """Tell the admins. Never raises: a canary that dies in its own alerting
    reports a clean sweep by exiting the same way a clean sweep would."""
    bad = canary.failures(results)
    text = _canary_report(results, backups, site)
    # The subject is what gets read on a phone, so the worst thing wins it.
    if site is not None and site.down:
        subject = "Milsurp canary: THE SITE IS DOWN"
    elif site is not None and site.unhappy:
        subject = "Milsurp canary: the site is struggling"
    elif backups is not None and backups.stale and not bad:
        subject = "Milsurp canary: backups have stopped"
    else:
        subject = f"Milsurp canary: {len(bad)} of {len(results)} shops not answering"
    body = (
        "<pre style='font:13px/1.5 ui-monospace,Menlo,Consolas,monospace'>"
        + (text.replace("&", "&amp;").replace("<", "&lt;"))
        + "</pre>"
    )
    with session_scope() as session:
        admins = (
            session.execute(
                select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
            )
            .scalars()
            .all()
        )
        addresses = [user.email for user in admins if user.email]
    if not addresses:
        print("No active admin has an email address; nothing sent.", file=sys.stderr)
        return
    for address in addresses:
        try:
            mailer.send_html(address, subject, body, text_body=text)
        except mailer.MailError as exc:
            print(f"Could not mail {address}: {exc}", file=sys.stderr)
        else:
            print(f"Reported to {address}.")


def cmd_canary(args: argparse.Namespace) -> int:
    """Probe every enabled shop and exit non-zero if any went quiet.

    Exits 1 on a failure so a systemd timer marks the unit failed and the
    journal records it, and mails the admins when asked, because a failed
    oneshot nobody looks at is not "loudly".
    """
    config = get_config()
    with session_scope() as session:
        query = select(Site).order_by(Site.name)
        if args.site:
            query = query.where(Site.slug == args.site)
        elif not args.all:
            # Enabled only, by default: the canary's question is whether what
            # this machine actually scrapes is still working. A shop nobody
            # scans cannot go quiet in a way anyone would notice.
            query = query.where(Site.enabled.is_(True))
        sites = session.execute(query).scalars().all()
        wanted = [(site.slug, site.name) for site in sites]
    if not wanted:
        if args.site:
            print(f"No site with slug {args.site!r}.", file=sys.stderr)
        else:
            print("No sites are enabled. Use --all to check them anyway.", file=sys.stderr)
        return 1

    width = max(len(slug) for slug, _ in wanted)

    def show(probe: canary.Probe) -> None:
        status = f" HTTP {probe.status}" if probe.status else ""
        note = f"  {probe.detail}" if probe.detail and not probe.healthy else ""
        print(
            f"  {probe.slug:<{width}}  {_CANARY_MARK[probe.verdict]:<8} "
            f"{probe.items:>2} in {probe.seconds:5.1f}s{status}{note}",
            flush=True,
        )

    results = canary.sweep(
        config,
        [slug for slug, _ in wanted],
        want=args.items,
        budget=args.budget,
        skip_browser=args.skip_browser,
        progress=show,
    )

    # The backups are checked too, and reported in the same breath: a copy that
    # stopped leaving this machine four nights ago fails exactly the way a
    # vendor that stopped answering does -- quietly, with nothing to see.
    backups = canary.backup_health(config)

    # And the site itself, from outside. An application cannot report its own
    # absence, and this process is the only part of the deployment still
    # running when the service is not.
    site = canary.site_health(config)

    bad = canary.failures(results)
    print()
    if not bad and not backups.stale and not site.unhappy:
        shops = "shop" if len(results) == 1 else "shops"
        print(f"All {len(results)} {shops} answered with listings.")
        print(site.headline)
        if backups.configured:
            print(backups.headline)
        return 0
    print(_canary_report(results, backups, site))
    if args.email:
        _mail_canary(results, backups, site)
    return 1


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
        site_id = None
        if args.site:
            site = session.execute(select(Site).where(Site.slug == args.site)).scalar_one_or_none()
            if site is None:
                print(f"No site with slug '{args.site}'.", file=sys.stderr)
                return 1
            site_id = site.id

        # The marking itself lives in the service, because the Sites page has
        # a button for it now and two implementations of "which listings" is
        # two chances to disagree about it.
        total, by_site = scan_service.mark_for_refetch(
            session,
            site_id=site_id,
            limit=args.limit,
            only_unreadable=not (args.all or args.site),
            dry_run=args.dry_run,
        )

        slugs = {
            site.id: site.slug
            for site in session.execute(select(Site).where(Site.id.in_(by_site))).scalars()
        }

    verb = "Would clear" if args.dry_run else "Cleared"
    print(f"{verb} the detail mark on {total} listing(s).")
    for site_id, count in sorted(by_site.items(), key=lambda pair: -pair[1]):
        print(f"  {count:6d}  {slugs.get(site_id, site_id)}")
    if total and not args.dry_run:
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
        "--limit",
        type=int,
        help="Mark at most this many, stalest product page first. A whole site "
        "is not always the right bite: re-reading one of 976 listings that "
        "carry a dozen photographs each queues five figures of downloads.",
    )
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
    command.add_argument(
        "--fields",
        default=",".join(RECOMPUTABLE),
        metavar="caliber,country,...",
        help="Which of them --recompute is allowed to overwrite. Defaults to all "
        f"of {', '.join(RECOMPUTABLE)}. Narrow it when a rule change affects one "
        "field and the others would pay for it: correcting 172 calibers after a "
        "caliber fix costs 138 listings their manufacturer, because a maker the "
        "vendor supplied cannot be re-derived from the text and comes back only "
        "on that site's next scan.",
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
    armory_qualify = armory_sub.add_parser(
        "qualify",
        help="Rename bare designations to name the firm already on the row.",
    )
    armory_qualify.add_argument(
        "--apply", action="store_true", help="Carry the plan out rather than printing it."
    )

    armory_tidy = armory_sub.add_parser(
        "tidy",
        help="Fill rows from their own listings; switch off ones that say nothing.",
    )
    armory_tidy.add_argument(
        "--apply", action="store_true", help="Carry the plan out rather than printing it."
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


def _add_account_parsers(sub: argparse._SubParsersAction) -> None:
    """The commands that act on one account. Grouped out of build_parser to
    keep it under the statement ceiling, and grouped together because these are
    the two an administrator reaches for when somebody cannot get in.
    """
    passwd = sub.add_parser("passwd", help="Change an account's password.")
    passwd.add_argument("username")
    passwd.add_argument("--password", help="Set non-interactively.")
    passwd.set_defaults(func=cmd_passwd)

    command = sub.add_parser("twofactor", help="Show or switch off two-factor for an account.")
    command.add_argument("username")
    command.add_argument(
        "--disable",
        action="store_true",
        help="Turn it off and sign out every existing session. The way back in "
        "when the phone and the recovery codes are both gone.",
    )
    command.set_defaults(func=cmd_twofactor)


def _add_scheduled_parsers(sub: argparse._SubParsersAction) -> None:
    """The commands a timer runs rather than a person: housekeeping and the
    canary. Grouped out of build_parser to keep it under the statement
    ceiling, and grouped *together* because these two are what
    debian/milsurp.milsurp-*.timer actually invoke.
    """
    sub.add_parser("prune-images", help="Delete image files no listing references.").set_defaults(
        func=cmd_prune_images
    )

    catch_up = sub.add_parser(
        "catch-up",
        help="Re-apply this version's rules to rows already stored (idempotent).",
    )
    catch_up.add_argument(
        "--dry-run", action="store_true", help="Report what each step would do and change nothing."
    )
    catch_up.set_defaults(func=cmd_catch_up)

    canary_cmd = sub.add_parser(
        "canary",
        help="Check every enabled shop still answers and still parses; exit 1 if any does not.",
    )
    canary_cmd.add_argument("--site", help="Check one slug instead of every enabled site.")
    canary_cmd.add_argument(
        "--all",
        action="store_true",
        help="Include sites that are registered but disabled.",
    )
    canary_cmd.add_argument(
        "--items",
        type=int,
        default=canary.DEFAULT_WANT,
        help=f"Listings to see before a shop counts as healthy (default {canary.DEFAULT_WANT}).",
    )
    canary_cmd.add_argument(
        "--budget",
        type=float,
        default=canary.DEFAULT_BUDGET,
        help=f"Seconds to allow each shop (default {canary.DEFAULT_BUDGET:.0f}).",
    )
    canary_cmd.add_argument(
        "--skip-browser",
        action="store_true",
        help="Leave out sites needing Selenium, for a host without Chrome.",
    )
    canary_cmd.add_argument(
        "--email", action="store_true", help="Mail the admins when anything failed."
    )
    canary_cmd.set_defaults(func=cmd_canary)


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

    _add_account_parsers(sub)

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

    _add_scheduled_parsers(sub)

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
