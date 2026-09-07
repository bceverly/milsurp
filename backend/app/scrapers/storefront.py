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
PLACEHOLDER = re.compile(r"^data:|/(?:placeholder|spacer|blank)[.-]", re.I)

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
        if match.group("url").strip() and not PLACEHOLDER.match(match.group("url").strip())
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
        if isinstance(value, str) and value.strip() and not PLACEHOLDER.match(value.strip()):
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
