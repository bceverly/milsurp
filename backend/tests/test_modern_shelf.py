"""The modern police trade-in shelf in the seed armory.

This catalog is a *milsurp* catalog, and four of its vendors sell a modern
service-pistol shelf beside it -- Recoil Gun Works, AIM Surplus, Officer Store,
Arms Unlimited. Before these rows the armory could not name any of it: Officer
Store matched 0 of 14 listings, Recoil 8 of 229, AIM 11 of 180.

The rows themselves are data and live in ``app/seed/armory.yaml``. What is
tested here is the thing that makes a modern row *dangerous* in a milsurp
catalog, which is that its designations collide with real service rifles.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

SEED = pathlib.Path(__file__).resolve().parents[1] / "app" / "seed" / "armory.yaml"


@pytest.fixture(scope="module")
def armory_file() -> dict:
    return yaml.safe_load(SEED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models(armory_file) -> list[dict]:
    return armory_file["models"]


class TestTheDesignationsDoNotCollide:
    """Two of these were caught by measurement rather than by reading.

    A bare ``G43`` alias on the Glock 43 matched a **Walther Gewehr 43** --
    "WWII German Walther 'ac 44' G43 Semi-Auto Rifle 8mm Mauser" -- and a bare
    ``G36`` matched a **Heckler & Koch G36**. Both of those guns are in this
    catalog. The aliases are qualified with the marque instead, which still
    catches "Glock G23 Gen 4", the shape the bare form was for.
    """

    def test_no_glock_carries_a_bare_g_number_alias(self, models):
        for row in models:
            if not row["name"].startswith("Glock "):
                continue
            for alias in row.get("aliases") or []:
                text = str(alias)
                bare = len(text) > 1 and text[0] in "Gg" and text[1].isdigit()
                assert not bare, (
                    f"{row['name']} carries the bare alias {text!r}. G43 is a Walther "
                    f"Gewehr 43 and G36 a Heckler & Koch, both of which are in this "
                    f"catalog -- qualify it as 'Glock {text}'."
                )

    def test_every_spelling_that_can_match_belongs_to_one_row(self, models):
        """Two rows answering to one string is a coin toss decided by position,
        and the loser's caliber and kind are silently the answer.

        Only rows that can actually match are compared. A *pending* row takes
        no part in matching at all, so the bare "AR15" and "M15" a scan
        proposed cannot collide with the AR-15 row that now claims those
        spellings -- they are the same question asked twice, and answering it
        is what promoting or merging one of them is for.
        """
        known = {
            ("M44", "Mosin-Nagant M44"),
            ("M91/30", "Mosin-Nagant M91/30"),
            ("91/30", "Mosin-Nagant M91/30"),
        }
        seen: dict[str, str] = {}
        clashes = []
        for row in models:
            if row.get("status", "pending") != "approved" or not row.get("enabled", True):
                continue
            for text in [row["name"], *(row.get("aliases") or [])]:
                key = str(text).strip().lower()
                if key in seen and seen[key] != row["name"]:
                    # The bare M44/M91/30 rows are carried over from the old
                    # one-maker-per-model table and are deliberately kept: see
                    # _facts_known in services/armory.py, where the row that
                    # can say more wins a tie.
                    if (str(text), row["name"]) in known:
                        continue
                    clashes.append(f"{text!r}: {seen[key]} and {row['name']}")
                seen.setdefault(key, row["name"])
        assert not clashes, "one spelling, two rows: " + "; ".join(clashes)


class TestTheModernRowsSayEnoughToBeWorthHaving:
    """54% of the approved armory said nothing at all when this was measured --
    no kind, no country, no caliber, no maker -- which is why blank-filling was
    1.5% of listings. A row added now has no excuse for joining them.
    """

    MODERN = (
        "Glock ",
        "Sig Sauer P",
        "Smith & Wesson M",
        "Beretta ",
        "Remington ",
        "Mossberg ",
        "Benelli ",
        "AR-1",
        "IWI ",
        "Ruger Mini",
    )

    def _modern(self, models):
        """The modern rows that are still in play.

        A merged row is a redirect rather than a model -- its listings belong to
        whatever it points at, which is where the facts live. "Remington 1903"
        was proposed from a title the M1903 Springfield's aliases could not
        catch ("1943 Remington 1903 A3 Rifle"), and folding it into that row is
        what put the kind and country right; asking the husk to state them
        would ask for the fact to be written down twice.
        """
        return [
            r
            for r in models
            if str(r["name"]).startswith(self.MODERN)
            and r.get("status") != "merged"
            and r.get("enabled") is not False
        ]

    def test_they_exist(self, models):
        assert len(self._modern(models)) >= 40

    def test_each_states_a_kind_and_a_country(self, models):
        for row in self._modern(models):
            assert row.get("kind"), f"{row['name']} does not say what kind of gun it is"
            assert row.get("country"), f"{row['name']} does not say where the pattern is from"

    def test_a_row_names_a_caliber_only_when_there_is_no_choice(self, models):
        """The rule the whole armory runs on. A Glock's number encodes its
        cartridge, so those state one; an AR-15 is 5.56, .223 Wylde or .300
        Blackout depending on the upper, so it states none rather than picking.
        """
        by_name = {r["name"]: r for r in models}
        # A Glock's number encodes its cartridge, so the row states it.
        assert by_name["Glock 22"]["calibers"] == [".40 S&W"]
        assert by_name["Glock 21"]["calibers"] == [".45 ACP"]
        # A P229 was sold in 9mm, .40 S&W and .357 Sig, and the designation
        # does not say which this one is. Same for the M&P Shield.
        assert not by_name["Sig Sauer P229"].get("calibers")
        assert not by_name["Smith & Wesson M&P Shield"].get("calibers")
        # And a Remington 700 is chambered in more cartridges than this
        # catalog has rows for.
        assert not by_name["Remington 700"].get("calibers")

    def test_the_calibers_they_name_are_rows_in_the_same_file(self, armory_file):
        """A caliber named here and absent from the calibers list is dropped on
        the floor by the seeder, silently -- see armory.seed()."""
        known = {str(c["name"]).strip().lower() for c in armory_file["calibers"]}
        for row in self._modern(armory_file["models"]):
            for caliber in row.get("calibers") or []:
                assert (
                    str(caliber).strip().lower() in known
                ), f"{row['name']} names {caliber!r}, which is not a caliber row"

    def test_the_makers_they_name_are_rows_in_the_same_file(self, armory_file):
        known = {str(m["name"]).strip().lower() for m in armory_file["manufacturers"]}
        for row in self._modern(armory_file["models"]):
            for maker in row.get("manufacturers") or []:
                assert (
                    str(maker).strip().lower() in known
                ), f"{row['name']} names {maker!r}, which is not a manufacturer row"


class TestTheModernMakersSayWhereTheyAre:
    """Country is the field these rows are really for: of the police-shelf
    listings, far more were missing a country than a caliber.

    Stated as "whichever of these are here must say where they are", not "all
    of these must be here". The seed file is a curated document and the admin
    who curates it is entitled to delete a row -- LMT was, for matching one
    listing -- or to rename one, as IWI was to "Israel Weapon Industries" once
    a spelling could be promoted. A test demanding the original list back would
    be fighting the person the file belongs to.

    Presence is still checked in the aggregate, so the whole block cannot
    quietly disappear -- which is how `country` went missing from all 99 makers
    at once when the exporter did not know about the column.
    """

    ADDED = (
        "Mossberg",
        "Bushmaster",
        "Daniel Defense",
        "Armalite",
        "Stag Arms",
        "LMT",
        "JP Enterprises",
        "IWI",
        "Israel Weapon Industries",
        "DPMS",
        "Windham Weaponry",
        "Benelli",
        "Kimber",
    )

    def _present(self, armory_file):
        by_name = {m["name"]: m for m in armory_file["manufacturers"]}
        return {name: by_name[name] for name in self.ADDED if name in by_name}

    def test_the_ones_still_here_say_where_they_are(self, armory_file):
        for name, row in self._present(armory_file).items():
            assert row.get("country"), (
                f"{name} does not say where it is. Country is what these rows were "
                f"added for -- see the class docstring."
            )

    def test_most_of_the_shelf_is_still_here(self, armory_file):
        """One or two removed is curation; ten missing is an export that lost
        them."""
        present = self._present(armory_file)
        assert len(present) >= 8, f"only {len(present)} of the modern makers remain"
