"""Helpers shared by the hosted-storefront scrapers.

WooCommerce and BigCommerce are different platforms with the same problems: a
grid of product cards, a price that has to be read past a struck-through
original, and images that arrive lazily behind a placeholder. Those three
answers belong in one place; everything platform-specific stays in the module
that knows about that platform.
"""

from __future__ import annotations

import re

from bs4 import Tag

#: A lazy-loading placeholder rather than a photograph.
#:
#: The names are the ones themes actually use, plus a blanket rule: **a product
#: photograph is never an SVG.** These are raster catalogs -- every real image
#: is a jpg, png or webp -- so an SVG in an image slot is furniture: a spinner,
#: a placeholder, an icon. DuPage Trading's theme puts
#: ``.../img/loading.svg`` in the ``src`` of every product image and the real
#: photograph in ``data-src``, which queued 23 placeholders beside 23 real
#: photographs and finished every scan PARTIAL with "23 of 46 photo(s) could
#: not be fetched".
#:
#: Costless to refuse: the image store rejects an SVG on arrival anyway
#: ("unsupported content type image/svg+xml"), so nothing that could have been
#: stored is being dropped -- only the attempt, and the warning it produced.
#:
#: Searched, not matched. It used to be anchored with ``.match()``, which meant
#: the name rule only ever fired on a root-relative ``src="/img/spacer.gif"``
#: and never on the absolute CDN URLs these shops actually emit -- so it had
#: been half dead for as long as it has existed. ``^data:`` carries its own
#: anchor and still only matches at the start.
PLACEHOLDER = re.compile(r"^data:|/(?:placeholder|spacer|blank|loading)[.-]|\.svg(?:$|[?#])", re.I)

PRICE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]{2})?)")

#: A photograph placed by CSS rather than by an ``<img>``.
#:
#: ``style="background-image:url(https://…/rifle.png);background-size: contain"``
#: — which is how a page builder puts a picture on a div. CO Gun Sales' whole
#: catalog grid is built this way and carries no ``<img>`` at all, so every one
#: of their 116 listings arrived with no photograph.
_CSS_BACKGROUND = re.compile(
    r"background(?:-image)?\s*:[^;]*url\(\s*(['\"]?)(?P<url>[^'\")]+)\1\s*\)", re.I
)


def background_images(tag: Tag) -> list[str]:
    """Image URLs a tag places through a CSS ``background-image``."""
    style = tag.get("style")
    if not isinstance(style, str):
        return []
    return [
        match.group("url").strip()
        for match in _CSS_BACKGROUND.finditer(style)
        if match.group("url").strip() and not PLACEHOLDER.search(match.group("url").strip())
    ]


def parse_price(text: str) -> float | None:
    match = PRICE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:  # pragma: no cover - the pattern guarantees digits
        return None


def image_sources(tag: Tag) -> list[str]:
    """Every image URL an ``<img>`` offers, best first.

    Themes lazy-load, so the ``src`` is often a placeholder and the real URL is
    in ``data-src``, ``data-large_image`` or the largest entry of a ``srcset``.
    """
    found: list[str] = []
    for attribute in ("data-large_image", "data-src", "data-lazy-src", "src"):
        value = tag.get(attribute)
        if isinstance(value, str) and value.strip() and not PLACEHOLDER.search(value.strip()):
            found.append(value.strip())
    for attribute in ("srcset", "data-srcset"):
        value = tag.get(attribute)
        if not isinstance(value, str):
            continue
        widths: list[tuple[int, str]] = []
        for candidate in value.split(","):
            parts = candidate.split()
            if not parts:
                continue
            width = 0
            if len(parts) > 1 and parts[1].endswith("w"):
                digits = parts[1][:-1]
                width = int(digits) if digits.isdigit() else 0
            widths.append((width, parts[0]))
        found.extend(url for _width, url in sorted(widths, reverse=True))
    return found
