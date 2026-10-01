"""The Carcano cavalry carbine, against the shipped armory as production runs it.

Its own row since 2026-10-01: before it, eleven listings of the Moschetto Mod.
91 per Cavalleria were either unmatched or filed under the M91 *rifle*, whose
name sits inside "Carcano M91 Moschetto Cavalry Carbine". The spellings are
the carbine's alone, and these titles -- every one a real vendor's -- hold
both halves of that: the carbines go to the carbine, and the cavalry carbines
of other patterns stay where they were.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, FirearmModel
from app.services import armory

CAVALRY = "Carcano M91 Cavalry Carbine"


@pytest.fixture
def shipped(seeded):
    """The shipped file loaded, with each row in the state the file gives it.

    armory.seed() brings every row in awaiting approval, deliberately; the
    matcher reads only approved rows, so the file's own statuses are applied
    here to match what a production armory exported into it looks like.
    """
    armory.seed(seeded)
    # The session does not autoflush, so the rows seed() added are invisible
    # to the query below until they are written.
    seeded.commit()
    approved = {
        row["name"]
        for rows in yaml.safe_load(armory.SEED_FILE.read_text()).values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and row.get("status") == "approved" and row.get("enabled", True)
    }
    for model in seeded.query(FirearmModel).filter(FirearmModel.name.in_(approved)):
        model.status = ArmoryStatus.APPROVED
    seeded.commit()
    armory.invalidate()
    yield seeded
    armory.invalidate()


@pytest.mark.parametrize(
    "title",
    [
        "Italian Carcano M.91 Cavalry Carbine, 6.5×52, 17.7″ Barrel, Folding Bayo, C&R Rifle",
        'Italian M91 Carcano Cavalry Carbine - 17.5" Barrel 6.5 Carcano 6 Rd Capacity',
        "WWII Italian Carcano M91 Moschetto Cavalry Carbine 6.5x52mm with Folding Bayonet",
        "Early Configuration 1891 Carcano Carbine, Serial Number G3620",
        "ITALY 1891 CARCANO MOSCHETTO",
        "FNA BRESCIA CARCANO MOSHETTO M91",
        "CARCANO MODEL 91 CARBINE",
    ],
)
def test_the_moschetto_is_the_carbine(shipped, title):
    assert armory.match(shipped, title).model == CAVALRY


@pytest.mark.parametrize(
    "title",
    [
        # Other patterns' cavalry carbines, which the obvious spellings take.
        "C Grade M38 Carcano Cavalry Carbine, Cal. 7.35×51",
        "Argentine Model 1891 Cavalry Carbine",
        # And the rifles and short rifles, which stay theirs.
        "WWI Italian Roma Arsenal Model 1891 Carcano Long Rifle 6.5x52mm",
        "BERETTA 1891/38 CARCANO CARBINE",
        "B grade 1891/28 Carcano Carbine 6.5X52 Second Model TS from Ethiopia",
        "TERNI ARSENAL CARCANO 91/24 CARBINE",
    ],
)
def test_nothing_else_is(shipped, title):
    assert armory.match(shipped, title).model != CAVALRY


def test_the_file_places_it_ahead_of_the_rifle(shipped):
    """Seeded at the default it lost the tie to the older M91 row."""
    rows = {
        row.name: row.position
        for row in shipped.query(FirearmModel).filter(FirearmModel.name.like("Carcano M91%"))
    }
    assert rows[CAVALRY] < rows["Carcano M91"]
