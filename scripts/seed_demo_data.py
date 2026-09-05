#!/usr/bin/env python3
"""Load deterministic sample listings into the current database.

The end-to-end suite needs an inventory to click through, and a screenshot run
needs one that looks plausible. Scraping live vendor sites for either would be
slow, rude, and non-deterministic — the assertions would change every time a
vendor updated their catalog.

    python scripts/seed_demo_data.py            # add sample data
    python scripts/seed_demo_data.py --reset    # wipe listings first

Only ever run this against a disposable or development database; it writes
fabricated listings that are indistinguishable from scraped ones in the UI.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.config import get_config  # noqa: E402
from app.database import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Item,
    ItemPhoto,
    PriceHistory,
    ScanRun,
    ScanStatus,
    Site,
    utcnow,
)
from app.services import classify  # noqa: E402
from app.services.image_store import ImageStore  # noqa: E402

# (title, price, category, age_days, sold, previous_price)
# Chosen to exercise every UI state: new badges, price reductions, sold and
# de-listed items, missing prices, rifles, handguns and accessories.
LISTINGS: tuple[tuple[str, float | None, str, int, bool, float | None], ...] = (
    ("GERMAN K98 Mauser rifle, matching numbers", 1450.0, "Rifle", 1, False, None),
    ("RUSSIAN Mosin Nagant M91/30, Izhevsk 1943", 425.0, "Rifle", 2, False, 525.0),
    ("FINNISH M39 rifle, VKT, excellent bore", 1195.0, "Rifle", 3, False, None),
    ("BRITISH Lee-Enfield No.4 Mk I, 1943", 675.0, "Rifle", 4, False, 750.0),
    ("SWISS Schmidt-Rubin K31, matching", 895.0, "Rifle", 5, False, None),
    ("ITALIAN Carcano M91 carbine, 1918", 550.0, "Rifle", 8, False, None),
    ("JAPANESE Arisaka Type 99, mum intact", 985.0, "Rifle", 12, False, None),
    ("YUGOSLAV M48 Mauser, unissued", 599.0, "Rifle", 15, False, 649.0),
    ("CZECH vz.24 Mauser rifle", 725.0, "Rifle", 20, False, None),
    ("SWEDISH Model 1896 Mauser, Carl Gustaf", 1050.0, "Rifle", 25, False, None),
    ("US M1 Garand, Springfield Armory 1944", 1795.0, "Rifle", 6, False, None),
    ("US M1 Carbine, Inland Division", 1295.0, "Rifle", 30, True, None),
    ("GERMAN Luger P08, 1917 DWM", 3250.0, "Handgun", 2, False, None),
    ("RUSSIAN Tokarev TT-33, 1944", 675.0, "Handgun", 7, False, 725.0),
    ("SOVIET Makarov PM, East German", 550.0, "Handgun", 9, False, None),
    ("POLISH Radom Vis 35, Nazi-marked", 1875.0, "Handgun", 11, False, None),
    ("BRITISH Webley Mk VI revolver, 1918", 995.0, "Handgun", 18, False, None),
    ("CZECH CZ 52 pistol with holster", 425.0, "Handgun", 22, False, None),
    ("GERMAN Walther PP, wartime production", 850.0, "Handgun", 40, True, None),
    ("Bayonet, German S84/98 with scabbard", 145.0, "Accessory", 14, False, None),
    ("Stripper clips, 8mm Mauser, lot of 10", 25.0, "Accessory", 16, False, None),
    ("Original leather ammo pouch, Wehrmacht", 85.0, "Accessory", 28, False, None),
    ("MOSIN Nagant M38 carbine", None, "Rifle", 3, False, None),
    ("FRENCH MAS 36 rifle, 7.5x54", 795.0, "Rifle", 45, False, None),
)


# Brand palette, so the generated placeholders sit in the same design language
# as the rest of the UI.
_PLACEHOLDER_COLORS = (
    ((18, 49, 89), (10, 34, 64)),
    ((27, 75, 143), (18, 49, 89)),
    ((90, 100, 116), (43, 51, 64)),
    ((30, 122, 70), (17, 21, 28)),
)


def _make_placeholder_photos(store: ImageStore, item: Item, count: int) -> list[tuple[str, int]]:
    """Draw simple placeholder graphics for a demo listing.

    Deliberately abstract rather than a stock firearm photograph: these exist so
    the grid and gallery lay out realistically in screenshots, and it should be
    obvious at a glance that they are synthetic and not a real product image.

    Returns ``(relative_path, byte_size)`` per generated file.
    """
    from PIL import Image, ImageDraw

    written: list[tuple[str, int]] = []
    top, bottom = _PLACEHOLDER_COLORS[item.id % len(_PLACEHOLDER_COLORS)]

    for index in range(count):
        width, height = 1200, 900
        image = Image.new("RGB", (width, height), top)
        draw = ImageDraw.Draw(image)

        # Vertical gradient.
        for y in range(height):
            ratio = y / height
            draw.line(
                [(0, y), (width, y)],
                fill=tuple(int(top[c] + (bottom[c] - top[c]) * ratio) for c in range(3)),
            )

        # A long horizontal bar, echoing the proportions of a rifle photo, so
        # object-fit and the card aspect ratio are exercised realistically.
        bar_y = height // 2 + (index * 40) - 20
        draw.rounded_rectangle(
            [width * 0.10, bar_y - 26, width * 0.90, bar_y + 26],
            radius=14,
            fill=(231, 237, 245),
        )
        draw.rounded_rectangle(
            [width * 0.10, bar_y - 8, width * 0.42, bar_y + 34],
            radius=10,
            fill=(199, 206, 219),
        )

        label = f"SAMPLE {index + 1}/{count}"
        draw.text((width * 0.10, height * 0.10), label, fill=(199, 206, 219))
        draw.text((width * 0.10, height * 0.10 + 18), item.title[:52], fill=(255, 255, 255))

        relative = f"demo/{item.id:04d}-{index}.jpg"
        target = store.absolute_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="JPEG", quality=86, optimize=True)
        written.append((relative, target.stat().st_size))

    return written


def seed(  # noqa: PLR0912 - a linear fixture builder; branches are per-field
    reset: bool = False, quiet: bool = False
) -> int:
    now = utcnow()
    config = get_config()
    config.ensure_directories()
    store = ImageStore(config)
    with session_scope() as session:
        sites = session.execute(select(Site).order_by(Site.id)).scalars().all()
        if not sites:
            print("No sites registered — run 'make init' first.", file=sys.stderr)
            return 1

        if reset:
            for item in session.execute(select(Item)).scalars().all():
                session.delete(item)
            session.commit()
            if not quiet:
                print("  Cleared existing listings.")

        created = 0
        for index, (title, price, category, age_days, sold, previous) in enumerate(LISTINGS):
            # Spread the catalog across every registered site.
            site = sites[index % len(sites)]
            key = f"demo-{index:03d}"

            existing = session.execute(
                select(Item).where(Item.site_id == site.id, Item.external_key == key)
            ).scalar_one_or_none()
            if existing is not None:
                continue

            first_seen = now - timedelta(days=age_days, hours=index)
            derived = classify.enrich(title, None, price)

            item = Item(
                site_id=site.id,
                external_key=key,
                url=f"{site.base_url.rstrip('/')}/demo/{key}",
                title=title,
                description=(
                    f"{title}. Collector-grade example in the condition described. "
                    "Bore is bright with strong rifling. Sold as a curio and relic."
                ),
                category=category,
                caliber=derived["caliber"],
                country=derived["country"],
                manufacturer=derived["manufacturer"],
                condition=derived["condition"],
                is_rifle=derived["is_rifle"],
                is_pistol=derived["is_pistol"],
                is_sold=sold,
                # A couple of older entries are de-listed, so that filter has
                # something to show.
                is_active=age_days < 40,
                first_seen_at=first_seen,
                last_seen_at=now,
                delisted_at=None if age_days < 40 else now - timedelta(days=1),
                current_price=price,
                previous_price=previous,
                lowest_price=min(p for p in (price, previous) if p is not None) if price else None,
                highest_price=max(p for p in (price, previous) if p is not None) if price else None,
                price_changed_at=(now - timedelta(hours=index + 1)) if previous else None,
            )
            session.add(item)
            session.flush()

            # One to four photos, varying so the gallery and its thumbnail strip
            # both appear in screenshots.
            photo_count = 1 + (index % 4)
            for position, (relative, size) in enumerate(
                _make_placeholder_photos(store, item, photo_count)
            ):
                session.add(
                    ItemPhoto(
                        item_id=item.id,
                        source_url=f"https://example.invalid/demo/{item.id}/{position}.jpg",
                        filename=relative,
                        # Small enough that the API serves it for both variants.
                        thumb_filename=relative,
                        content_type="image/jpeg",
                        bytes=size,
                        thumb_bytes=size,
                        width=1200,
                        height=900,
                        position=position,
                        downloaded_at=now,
                    )
                )

            if price is not None:
                if previous is not None:
                    session.add(
                        PriceHistory(
                            item_id=item.id,
                            price=previous,
                            observed_at=first_seen + timedelta(hours=1),
                        )
                    )
                session.add(
                    PriceHistory(
                        item_id=item.id,
                        price=price,
                        observed_at=now - timedelta(hours=index + 1),
                    )
                )
            created += 1

        # A little scan history, so the admin views are not empty either.
        for site in sites:
            if (
                session.execute(
                    select(ScanRun).where(ScanRun.site_id == site.id).limit(1)
                ).scalar_one_or_none()
                is not None
            ):
                continue
            for run_index in range(3):
                started = now - timedelta(hours=run_index * 12 + 1)
                session.add(
                    ScanRun(
                        site_id=site.id,
                        status=ScanStatus.SUCCESS if run_index else ScanStatus.PARTIAL,
                        trigger="scheduled",
                        started_at=started,
                        finished_at=started + timedelta(minutes=2, seconds=14),
                        duration_seconds=134.2,
                        items_found=len(LISTINGS) // len(sites),
                        items_new=2 if run_index == 0 else 0,
                        items_updated=10,
                        price_changes=1,
                        price_drops=1,
                        log=f"[00:00:0{run_index}] Demo scan record.",
                        error_message=None if run_index else "one page could not be fetched",
                    )
                )
            site.last_scan_at = now - timedelta(hours=1)
            site.last_success_at = now - timedelta(hours=1)

        session.commit()

    if not quiet:
        print(f"  Seeded {created} sample listing(s) across {len(sites)} site(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load sample listings for tests and screenshots.")
    parser.add_argument("--reset", action="store_true", help="Delete existing listings first.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    return seed(reset=args.reset, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
