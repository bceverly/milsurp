"""Magazines and speedloaders that fit the guns somebody owns.

Layer 2 of "Upgrades and accessories for the guns you own" (ROADMAP.md),
2026-10-28. The plan was to read accessory sections of shops already scanned
and match their titles to owned models; the survey of the specialists turned
up something better, stores that say themselves which guns a product fits,
and that is the 80% asked for without guessing from a title:

* **GunMag Warehouse** ("typically where i find magazines at the lowest
  prices"): Magento with an Algolia index, as at Silencer Central, whose
  records carry ``compatible_firearm`` -- "Glock 17, Glock 19, Glock 26, ...
  Shadow Systems CR920" on one PMAG. 14,000 in stock, so it is asked only
  about the models in readers' collections, one query each, with the secured
  key read from its page every run.
* **Speed Beez**: revolver speedloader pouches and cases, a WooCommerce Store
  API, whose "Gun Model" attribute lists the revolvers ("GP100 -- .357, 6
  Shot"). 265 products, all read.

**Which owned gun a store's line names is the armory's call**: each line is
run through the same matcher a listing is, so "S&W M&P 9" and "Smith & Wesson
M&P9" are the same model. A line the armory cannot place fits nobody. Offers
are kept apart from the browse catalog (``AccessoryOffer``), refreshed daily
by the scheduler and by ``cli.py fitting-refresh``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AccessoryOffer, CollectionItem, FirearmModel, utcnow
from ..scrapers.base import ScrapeContext, ScrapeError, flatten_html, normalize_whitespace
from . import armory

log = logging.getLogger("milsurp.fitting")

GUNMAG = "gunmag-warehouse"
SPEEDBEEZ = "speed-beez"
#: Where each offer came from, as a reader reads it.
SOURCE_NAMES = {GUNMAG: "GunMag Warehouse", SPEEDBEEZ: "Speed Beez"}

GUNMAG_PAGE = "https://gunmagwarehouse.com/"
SPEEDBEEZ_API = "https://www.speedbeez.com/wp-json/wc/store/v1/products"
#: The most offers kept per owned model from one query.
PER_MODEL = 100
#: Shown per gun on the page; the rest are counted.
PER_GUN = 12

_SETTING = re.compile(r'"(applicationId|apiKey|indexName)":"([^"]+)"')
#: "GP100 -- .357, 6 Shot" (an en dash in the shop's terms): the revolver is before it.
_MODEL_PART = re.compile("\\s+[\u2013\u2014-]\\s+.*$")


@dataclass
class Refreshed:
    kept: dict[str, int] = field(default_factory=dict)
    asked: int = 0


def owned_models(session: Session) -> list[FirearmModel]:
    """The armory models somebody's collection holds."""
    ids = set(
        session.execute(
            select(CollectionItem.firearm_model_id).where(
                CollectionItem.firearm_model_id.is_not(None)
            )
        ).scalars()
    )
    if not ids:
        return []
    return list(
        session.execute(select(FirearmModel).where(FirearmModel.id.in_(ids))).scalars().all()
    )


def _fits_any(session: Session, lines: Iterable[str], model_ids: set[int]) -> bool:
    registry = armory.model_registry(session)
    return any(registry.match(line).model_id in model_ids for line in lines if line)


def _gunmag(session: Session, ctx: ScrapeContext, models: list[FirearmModel]) -> list[dict]:
    """In-stock magazines GunMag Warehouse says fit one of ``models``."""
    page = ctx.get_text(GUNMAG_PAGE)
    settings: dict[str, str] = {}
    for name, value in _SETTING.findall(page):
        settings.setdefault(name, value)
    if {"applicationId", "apiKey", "indexName"} - set(settings):
        raise ScrapeError("GunMag Warehouse no longer publishes its search settings.")
    app_id = settings["applicationId"]
    endpoint = f"https://{app_id}-dsn.algolia.net/1/indexes/{settings['indexName']}_products"
    ctx.keep_at_least(f"https://{app_id}-dsn.algolia.net/", 2.0)
    found: dict[str, dict] = {}
    for model in models:
        ctx.check_stop()
        query = urlencode(
            {
                "x-algolia-application-id": app_id,
                "x-algolia-api-key": settings["apiKey"],
                "query": model.name,
                "hitsPerPage": PER_MODEL,
                "facetFilters": json.dumps(["in_stock:1"]),
            }
        )
        try:
            document = json.loads(ctx.get_text(f"{endpoint}?{query}"))
        except (ValueError, ScrapeError) as exc:
            log.warning("GunMag Warehouse did not answer for %s: %s", model.name, exc)
            continue
        for hit in document.get("hits") or []:
            fits = [str(line) for line in hit.get("compatible_firearm") or [] if line]
            key = str(hit.get("objectID") or "")
            if not key or not fits or key in found:
                continue
            if not _fits_any(session, fits, {model.id}):
                continue
            price = ((hit.get("price") or {}).get("USD") or {}).get("default")
            found[key] = {
                "external_key": key,
                "kind": "magazine",
                "title": normalize_whitespace(str(hit.get("name") or "")),
                "url": str(hit.get("url") or ""),
                "price": float(price) if isinstance(price, int | float) else None,
                "in_stock": bool(hit.get("in_stock")),
                "image_url": hit.get("thumbnail_url") or hit.get("image_url"),
                "maker": hit.get("am_brand"),
                "fits": "\n".join(fits),
            }
    return [offer for offer in found.values() if offer["title"] and offer["url"]]


def _speedbeez(session: Session, ctx: ScrapeContext, model_ids: set[int]) -> list[dict]:
    """Speed Beez's products whose "Gun Model" names an owned revolver."""
    found: list[dict] = []
    for page in range(1, 20):
        ctx.check_stop()
        url = f"{SPEEDBEEZ_API}?{urlencode({'per_page': 100, 'page': page})}"
        try:
            products = json.loads(ctx.get_text(url))
        except (ValueError, ScrapeError) as exc:
            log.warning("Speed Beez did not answer: %s", exc)
            break
        if not isinstance(products, list) or not products:
            break
        for product in products:
            fits = []
            for attribute in product.get("attributes") or []:
                if attribute.get("name") == "Gun Model":
                    for term in attribute.get("terms") or []:
                        name = _MODEL_PART.sub("", str(term.get("name") or ""))
                        fits.append(
                            normalize_whitespace(name.replace("\u2122", "").replace("\u00ae", ""))
                        )
            if not fits or not _fits_any(session, fits, model_ids):
                continue
            prices = product.get("prices") or {}
            try:
                price = int(prices.get("price") or 0) / 10 ** int(
                    prices.get("currency_minor_unit") or 2
                )
            except (TypeError, ValueError):
                price = 0
            images = product.get("images") or []
            found.append(
                {
                    "external_key": str(product.get("id")),
                    "kind": "speedloader",
                    "title": normalize_whitespace(flatten_html(product.get("name")) or ""),
                    "url": str(product.get("permalink") or ""),
                    "price": price or None,
                    "in_stock": bool(product.get("is_in_stock")),
                    "image_url": images[0].get("thumbnail") if images else None,
                    "maker": "Speed Beez",
                    "fits": "\n".join(fits),
                }
            )
        if len(products) < 100:
            break
    return [offer for offer in found if offer["title"] and offer["url"]]


def _keep(session: Session, source: str, offers: list[dict]) -> int:
    """Replace one source's offers with this run's."""
    now = utcnow()
    session.execute(delete(AccessoryOffer).where(AccessoryOffer.source == source))
    for offer in offers:
        session.add(AccessoryOffer(source=source, refreshed_at=now, **offer))
    session.commit()
    return len(offers)


def refresh(
    session: Session, ctx: ScrapeContext, *, log_line: Callable[[str], None] = log.info
) -> Refreshed:
    """Ask each store about the models readers own; keep what fits.

    A store that does not answer keeps yesterday's offers rather than losing
    them, because an empty answer from a failure is not an empty shelf.
    """
    result = Refreshed()
    models = owned_models(session)
    result.asked = len(models)
    if not models:
        log_line("No collection holds a model the armory knows; nothing to ask about.")
        return result
    for source, read in (
        (GUNMAG, lambda: _gunmag(session, ctx, models)),
        (SPEEDBEEZ, lambda: _speedbeez(session, ctx, {model.id for model in models})),
    ):
        try:
            offers = read()
        except ScrapeError as exc:
            log_line(f"{SOURCE_NAMES[source]}: {exc}; keeping what was there.")
            continue
        result.kept[source] = _keep(session, source, offers)
        log_line(f"{SOURCE_NAMES[source]}: {result.kept[source]} offer(s) that fit.")
    return result


@dataclass
class Offer:
    source: str
    kind: str
    title: str
    url: str
    price: float | None
    in_stock: bool
    image_url: str | None


def for_model(
    session: Session, model_id: int, offers: list[AccessoryOffer] | None = None
) -> list[Offer]:
    """What fits one owned model, cheapest in stock first."""
    registry = armory.model_registry(session)
    rows = offers if offers is not None else session.execute(select(AccessoryOffer)).scalars().all()
    found = []
    for row in rows:
        lines = (row.fits or "").splitlines()
        if any(registry.match(line).model_id == model_id for line in lines if line):
            found.append(
                Offer(
                    source=SOURCE_NAMES.get(row.source, row.source),
                    kind=row.kind,
                    title=row.title,
                    url=row.url,
                    price=row.price,
                    in_stock=row.in_stock,
                    image_url=row.image_url,
                )
            )
    found.sort(key=lambda offer: (not offer.in_stock, offer.price is None, offer.price or 0))
    return found


def all_offers(session: Session) -> list[AccessoryOffer]:
    return list(session.execute(select(AccessoryOffer)).scalars().all())


def as_dict(offer: Offer) -> dict[str, Any]:
    return vars(offer)
