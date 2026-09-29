"""A rebuild may not make a caliber vaguer.

On 2026-09-29 `reclassify --recompute --fields caliber` ran in production and
turned "7x57mm Mauser" into "7mm", "11mm Mauser" into "11mm" and ".44 Russian"
into ".44": re-reading a title found only the bore, where the stored value had
come from a richer source when the listing was scanned. 54 listings were put
back by hand from a snapshot.
"""

from __future__ import annotations

import pytest
from cli import _permitted

from app.models import Item
from app.services import provenance
from app.services.classify import is_vaguer


class TestVaguer:
    @pytest.mark.parametrize(
        ("new", "stored"),
        [
            ("7mm", "7x57mm Mauser"),
            ("11mm", "11mm Mauser"),
            (".44", ".44 Russian"),
            ("6.5mm", "6.5x50mm Arisaka"),
            ("8x50mmR", "8x50mmR Lebel"),
            (".577", ".577/450 Martini-Henry"),
            ("6mm", "6mm Flobert"),
        ],
    )
    def test_the_bore_alone_is_vaguer(self, new, stored):
        assert is_vaguer(new, stored)

    @pytest.mark.parametrize(
        ("new", "stored"),
        [
            (".45 ACP", ".25 ACP"),  # a different bore is a correction
            (".40 S&W", ".40"),  # more specific, not less
            (".30 Luger", "9mm Luger"),
            ("7mm", "7mm"),
            (None, ".32 ACP"),  # clearing is judged by the caller
        ],
    )
    def test_a_correction_is_not(self, new, stored):
        assert not is_vaguer(new, stored)


def _derived(caliber: str | None) -> Item:
    return Item(title="t", caliber=caliber, caliber_source=provenance.DERIVED)


class TestTheRebuild:
    def rebuild(self, item, value, *, is_firearm=True):
        protected: dict[str, int] = {}
        allowed = _permitted(
            item, {"caliber": value}, {"caliber"}, protected, is_firearm=is_firearm
        )
        return allowed["caliber"], protected

    def test_a_vaguer_answer_keeps_the_stored_one(self):
        caliber, protected = self.rebuild(_derived("7x57mm Mauser"), "7mm")
        assert caliber == "7x57mm Mauser"
        assert protected == {"caliber kept more specific": 1}

    def test_and_keeps_its_source(self):
        item = Item(title="t", caliber="11mm Mauser", caliber_source=provenance.CATALOG)
        self.rebuild(item, "11mm")
        assert item.caliber_source == provenance.CATALOG

    def test_a_firearm_is_not_left_with_nothing(self):
        caliber, _protected = self.rebuild(_derived(".32 ACP"), None)
        assert caliber == ".32 ACP"

    def test_but_a_bayonet_can_be(self):
        """What clearing is for: a bayonet that took the caliber of the rifle
        it fits has none of its own."""
        caliber, _protected = self.rebuild(_derived(".32 ACP"), None, is_firearm=False)
        assert caliber is None

    def test_a_correction_still_lands(self):
        item = _derived(".40")
        caliber, protected = self.rebuild(item, ".40 S&W")
        assert caliber == ".40 S&W"
        assert protected == {}
        assert item.caliber_source == provenance.DERIVED
