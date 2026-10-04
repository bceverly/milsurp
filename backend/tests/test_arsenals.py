"""Which arsenal made the gun, read among the factories of its model.

Measured on production 2026-10-04: 95% of Garand listings, 93% of carbines and
70% of Mosins name their arsenal, and the maker field said "Mosin-Nagant" on
every one of 65 M91/30s. A model's linked makers are its arsenals; a maker's
*marks* (``bcd``, ``SA``) count only inside its own models' listings; and the
most specific mention wins -- a mark over a name, a firm that is not the
pattern's own name, the title over the description, the earlier mention.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Manufacturer, Site
from app.services import armory, arsenals, manufacturers, provenance


def _maker(session, name, *, aliases=None, marks=None, status=ArmoryStatus.APPROVED, enabled=True):
    row = Manufacturer(name=name, aliases=aliases, marks=marks, status=status, enabled=enabled)
    session.add(row)
    return row


def _model(session, name, makers, *, aliases=None):
    row = FirearmModel(name=name, aliases=aliases, status=ArmoryStatus.APPROVED)
    row.manufacturers = makers
    session.add(row)
    return row


@pytest.fixture
def armory_rows(clean_db):
    s = clean_db
    mosin = _maker(s, "Mosin-Nagant", aliases="Mosin Nagant")
    tula, izhevsk = _maker(s, "Tula"), _maker(s, "Izhevsk", aliases="Izhmash")
    mauser = _maker(s, "Mauser", marks="byf\nS/42")
    gustloff = _maker(s, "Gustloff", aliases="Gustloff-Werke", marks="bcd")
    springfield = _maker(s, "Springfield", aliases="Springfield Armory", marks="SA")
    winchester = _maker(s, "Winchester", marks="WRA")
    pending = _maker(s, "Sestroryetsk", status=ArmoryStatus.PENDING)
    off = _maker(s, "Westinghouse", enabled=False)
    rows = {
        "m9130": _model(
            s,
            "Mosin-Nagant M91/30",
            [mosin, tula, izhevsk, pending, off],
            aliases="Mosin Nagant M91/30\n91/30",
        ),
        "k98": _model(s, "Karabiner 98k", [mauser, gustloff], aliases="K98k\nMauser K98k"),
        "garand": _model(s, "M1 Garand", [springfield, winchester], aliases="Garand"),
        "lonely": _model(s, "Lonely 1", [mauser]),
        "other": _model(s, "Other rifle", [tula, izhevsk]),
    }
    s.commit()
    arsenals.forget()
    return rows


def _for(session, model, title, description=None):
    return arsenals.arsenal_for(session, model.id, title, description)


class TestWhichArsenal:
    def test_the_factory_named_beats_the_pattern_named(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["m9130"], "Mosin Nagant M91/30 Izhevsk 1943") == "Izhevsk"

    def test_the_title_beats_the_description(self, clean_db, armory_rows):
        found = _for(clean_db, armory_rows["m9130"], "M91/30 Tula 1942", "Izhevsk bolt")
        assert found == "Tula"

    def test_the_description_counts_when_the_title_says_nothing(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["m9130"], "M91/30 rifle", "made by Izhmash") == "Izhevsk"

    def test_a_mark_beats_a_name(self, clean_db, armory_rows):
        """ "Mauser" there is the pattern; ``bcd`` is the factory."""
        assert _for(clean_db, armory_rows["k98"], "Mauser K98k bcd 43") == "Gustloff"
        assert _for(clean_db, armory_rows["k98"], "Mauser K98k byf 42") == "Mauser"

    def test_the_title_outranks_anything_the_description_names(self, clean_db, armory_rows):
        """A description quotes disclaimers and names the makers of parts.
        Measured on production: "Springfield M1903" in a title, and a
        disclaimer below it about Rock Island receivers."""
        rock_island = _maker(clean_db, "Rock Island Arsenal", aliases="Rock Island")
        springfield = clean_db.query(Manufacturer).filter_by(name="Springfield").one()
        m1903 = _model(clean_db, "M1903 Springfield", [springfield, rock_island])
        clean_db.commit()
        arsenals.forget()
        disclaimer = "any Rock Island Arsenal M1903 with a receiver serial below 285,508"
        assert _for(clean_db, m1903, "Springfield M1903 Rifle", disclaimer) == "Springfield"
        found = _for(clean_db, armory_rows["k98"], "Mauser K98k rifle", "receiver code bcd")
        assert found == "Mauser"

    def test_a_mention_of_a_part_is_not_the_maker(self, clean_db, armory_rows):
        """Seen on production: "vlb ZF-41 scope & duv mount" on a K98k sniper."""
        gustloff = clean_db.query(Manufacturer).filter_by(name="Gustloff").one()
        gustloff.marks = "bcd\nduv"
        clean_db.commit()
        arsenals.forget()
        rows = armory_rows["k98"]
        assert _for(clean_db, rows, "K98k sniper, ZF-41 scope & duv mount") is None
        assert _for(clean_db, rows, "K98k sniper, duv mount, bcd 43 receiver") == "Gustloff"

    def test_a_description_that_lists_factories_attributes_none(self, clean_db, armory_rows):
        """Seen on production: "(e.g., Mauser Oberndorf, Steyr, or Waffenwerke
        Brünn)" in a Yugoslav rework's description."""
        listed = "rebuilt from rifles by Tula or Izhevsk"
        assert _for(clean_db, armory_rows["m9130"], "M91/30 rifle", listed) is None
        assert _for(clean_db, armory_rows["m9130"], "M91/30 rifle", "an Izhevsk 1943") == "Izhevsk"

    def test_in_one_field_the_factory_beats_the_pattern_s_name(self, clean_db, armory_rows):
        enfield, savage = _maker(clean_db, "Enfield"), _maker(clean_db, "Savage")
        no4 = _model(
            clean_db, "Lee-Enfield No.4 Mk1", [enfield, savage], aliases="Lee Enfield No.4"
        )
        clean_db.commit()
        arsenals.forget()
        title = "WW2 Lee Enfield Lend-Lease No.4 rifle by Savage-Stevens"
        assert _for(clean_db, no4, title) == "Savage"

    def test_a_mark_is_a_whole_token(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["k98"], "K98k S/42 G code") == "Mauser"
        assert _for(clean_db, armory_rows["k98"], "K98k 1942 rifle, 42 dated") is None

    def test_a_mark_may_run_into_its_year(self, clean_db, armory_rows):
        """ "BYF45", "bcd43": the date written straight on, as dealers do --
        but a serial is not a mark, so exactly two digits."""
        assert _for(clean_db, armory_rows["k98"], "Mauser K98 BYF45 Rifle") == "Mauser"
        assert _for(clean_db, armory_rows["k98"], "Mauser K98k bcd43") == "Gustloff"
        assert _for(clean_db, armory_rows["garand"], "M1 Garand SA44") == "Springfield"
        assert _for(clean_db, armory_rows["garand"], "M1 Garand serial SA1168") is None

    def test_marks_count_only_on_their_own_models(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["garand"], "M1 Garand SA receiver") == "Springfield"
        assert _for(clean_db, armory_rows["garand"], "M1 Garand WRA 1944") == "Winchester"
        assert _for(clean_db, armory_rows["other"], "Other rifle SA") is None

    def test_a_modern_maker_is_not_the_wartime_one(self, clean_db):
        """Inland Manufacturing of Dayton makes reproductions; Inland Division
        of General Motors made the carbines. "Inland Mfg" is the modern firm,
        and the longer name wins where both begin."""
        s = clean_db
        inland = _maker(s, "Inland", aliases="Inland Division")
        modern = _maker(s, "Inland Manufacturing", aliases="Inland Mfg")
        ibm = _maker(s, "IBM", aliases="I.B.M.")
        carbine = _model(s, "M1 Carbine", [inland, modern, ibm])
        s.commit()
        arsenals.forget()
        assert _for(s, carbine, "Inland Mfg ILM150 M1A1 Paratrooper") == "Inland Manufacturing"
        assert _for(s, carbine, "Nice Inland M1A1 Paratrooper Carbine - 1944 mfg") == "Inland"
        assert _for(s, carbine, "WWII I.B.M. M1 Carbine") == "IBM"

    def test_the_longer_name_wins_where_both_begin(self, clean_db, armory_rows):
        rand = _maker(clean_db, "Remington Rand")
        remington = _maker(clean_db, "Remington")
        m1911 = _model(clean_db, "M1911A1", [remington, rand])
        clean_db.commit()
        arsenals.forget()
        assert _for(clean_db, m1911, "Remington Rand M1911A1 .45") == "Remington Rand"
        assert _for(clean_db, m1911, "Remington M1911A1 .45") == "Remington"

    def test_the_pattern_name_alone_is_still_an_answer(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["m9130"], "Mosin Nagant M91/30") == "Mosin-Nagant"

    def test_pending_and_disabled_makers_take_no_part(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["m9130"], "M91/30 Sestroryetsk") is None
        assert _for(clean_db, armory_rows["m9130"], "M91/30 Westinghouse") is None

    def test_one_maker_is_not_a_choice(self, clean_db, armory_rows):
        """A model with one maker already names it through fill_in."""
        assert _for(clean_db, armory_rows["lonely"], "Lonely 1 byf") is None

    def test_no_model_no_arsenal(self, clean_db, armory_rows):
        assert arsenals.arsenal_for(clean_db, None, "Izhevsk") is None


class TestWhoseWordItReplaces:
    @pytest.fixture
    def listing(self, clean_db, armory_rows):
        site = Site(slug="ars", name="Ars", base_url="https://a.test/")
        clean_db.add(site)
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="x",
            url="https://a.test/x",
            title="Mosin Nagant M91/30 Izhevsk 1943",
            is_rifle=True,
            firearm_model_id=armory_rows["m9130"].id,
            manufacturer="Mosin-Nagant",
        )
        clean_db.add(item)
        clean_db.commit()
        return item

    @pytest.mark.parametrize("source", [provenance.DERIVED, provenance.CATALOG])
    def test_a_guess_is_replaced(self, clean_db, listing, source):
        listing.manufacturer_source = source
        assert arsenals.apply(clean_db, listing) is True
        assert (listing.manufacturer, listing.manufacturer_source) == ("Izhevsk", "catalog")

    @pytest.mark.parametrize("source", [provenance.VENDOR, provenance.OVERRIDE, None])
    def test_a_vendor_a_person_or_an_unknown_origin_is_kept(self, clean_db, listing, source):
        listing.manufacturer_source = source
        assert arsenals.apply(clean_db, listing) is False
        assert listing.manufacturer == "Mosin-Nagant"

    def test_an_empty_maker_is_filled(self, clean_db, listing):
        listing.manufacturer = None
        assert arsenals.apply(clean_db, listing) is True
        assert listing.manufacturer == "Izhevsk"


class TestEveryPathReachesIt:
    def test_a_scan(self, clean_db, armory_rows):
        from app.scrapers.base import ScrapedItem
        from app.services import scan_service

        site = Site(slug="arsscan", name="ArsScan", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.commit()
        armory.invalidate()
        scraped = ScrapedItem(
            external_key="g1",
            url="https://s.test/g1",
            title="M1 Garand rifle, Winchester WRA receiver, 30-06",
        )
        item, _, _ = scan_service._upsert_item(
            clean_db, site, scraped, run=None, seen_at=scan_service.utcnow()
        )
        clean_db.commit()
        assert item.firearm_model_id == armory_rows["garand"].id
        assert item.manufacturer == "Winchester"

    def test_re_deriving_makers_keeps_the_arsenal(self, clean_db, armory_rows):
        site = Site(slug="arsre", name="ArsRe", base_url="https://r.test/")
        clean_db.add(site)
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="r",
            url="https://r.test/r",
            title="Mosin Nagant M91/30 Tula 1942",
            is_rifle=True,
            firearm_model_id=armory_rows["m9130"].id,
        )
        clean_db.add(item)
        clean_db.commit()
        manufacturers.invalidate()
        manufacturers.reprocess(clean_db, ["Mosin Nagant"])
        assert item.manufacturer == "Tula"
        item.manufacturer = "Mosin-Nagant"
        manufacturers.reprocess_everything(clean_db)
        assert item.manufacturer == "Tula"

    def test_the_backfill(self, clean_db, armory_rows):
        site = Site(slug="arsbf", name="ArsBf", base_url="https://b.test/")
        clean_db.add(site)
        clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key="b",
            url="https://b.test/b",
            title="Mauser K98k bcd 4",
            is_rifle=True,
            firearm_model_id=armory_rows["k98"].id,
            manufacturer="Mauser",
            manufacturer_source=provenance.DERIVED,
        )
        clean_db.add(item)
        clean_db.commit()
        assert arsenals.backfill(clean_db) == 1
        assert item.manufacturer == "Gustloff"
        assert arsenals.backfill(clean_db) == 0

    def test_an_armory_edit_forgets_the_compiled_table(self, clean_db, armory_rows):
        assert _for(clean_db, armory_rows["garand"], "M1 Garand IHC") is None
        harvester = _maker(clean_db, "International Harvester", aliases="IHC")
        armory_rows["garand"].manufacturers.append(harvester)
        clean_db.commit()
        armory.invalidate()
        assert _for(clean_db, armory_rows["garand"], "M1 Garand IHC") == "International Harvester"
