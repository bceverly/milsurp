"""Put right the M1917s filed as .303 British, and any P14 filed as .30-06.

The M1917 and the P14 are one rifle in two cartridges, and until
``classify.enfield_pattern`` existed the word "Enfield" alone decided: every
"CMP M1917 Enfield Service Grade" became a .303 British. Fixing how a listing
is read does not reach the listings already read, and a scan only ever fills
an empty caliber, so this corrects the stored ones. Run once by migration 0058.

A listing is corrected only where its caliber was a guess -- ``derived`` or
``catalog`` -- and its title states no cartridge. A vendor's field and a
person's correction are never touched, and neither is a title that says
".303" outright.

What decides is, first, the model the armory matched: a model whose only
caliber is .30-06 is not a .303, and the reverse -- that is a statement
somebody made about the rifle. Without a model, the title alone, read by the
same rule the classifier now uses.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from . import classify

log = logging.getLogger("milsurp.enfields")

_US, _BRITISH = ".30-06", ".303 British"


def _spellings(bind, wanted: str) -> tuple[str | None, set[str]]:
    """The caliber row that spells *wanted*: its name, and all its spellings."""
    rows = bind.execute(sa.text("SELECT name, aliases FROM calibers")).all()
    for name, aliases in rows:
        spelled = {name.lower(), *(a.strip().lower() for a in (aliases or "").splitlines())}
        spelled.discard("")
        if wanted.lower() in spelled:
            return name, spelled
    return None, {wanted.lower()}


def recalibrate(bind) -> int:
    """Correct the stored listings; returns how many changed."""
    m1917_name, m1917_spelled = _spellings(bind, _US)
    p14_name, p14_spelled = _spellings(bind, _BRITISH)
    if not m1917_name or not p14_name:
        return 0
    # The models stating exactly one caliber, and which.
    sole = dict(
        bind.execute(
            sa.text(
                "SELECT fmc.firearm_model_id, MIN(c.name) FROM firearm_model_calibers fmc "
                "JOIN calibers c ON c.id = fmc.caliber_id "
                "GROUP BY fmc.firearm_model_id HAVING COUNT(*) = 1"
            )
        ).all()
    )
    rows = bind.execute(
        sa.text(
            "SELECT id, title, caliber, firearm_model_id FROM items "
            "WHERE caliber_source IN ('derived', 'catalog') AND caliber IS NOT NULL"
        )
    ).all()
    changes: list[dict] = []
    for item_id, title, caliber, model_id in rows:
        held = caliber.lower()
        if held in m1917_spelled:
            other, other_name = _BRITISH, p14_name
        elif held in p14_spelled:
            other, other_name = _US, m1917_name
        else:
            continue
        if classify.states_a_cartridge(title):
            continue
        if model_id is not None and model_id in sole:
            right = sole[model_id] == other_name
        else:
            pattern = classify.enfield_pattern(classify.without_percentages((title or "").lower()))
            right = pattern == other
        if right:
            changes.append({"id": item_id, "caliber": other_name})
    if changes:
        bind.execute(sa.text("UPDATE items SET caliber = :caliber WHERE id = :id"), changes)
    log.info("Enfield calibers: corrected %s listing(s).", len(changes))
    return len(changes)
