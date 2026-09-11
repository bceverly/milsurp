"""The armory: models, calibers, approval and merging.

The catalog is the one place in this application that does not guess. Its
value is entirely in two properties, and most of what follows tests those:

  - Nothing pending decides anything. A scan may propose whatever it likes
    because a proposal is inert until a person promotes it.
  - The same cartridge is one row however the trade writes it, because a
    filter on ".32 ACP" that misses the "7.65mm Browning" listings is worse
    than no filter.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, Caliber, FirearmKind, FirearmModel, Manufacturer
from app.services import armory, classify


@pytest.fixture
def cartridge(seeded):
    row = Caliber(
        name=".32 ACP",
        aliases="7.65mm Browning\n7.65x17mm\n.32 Auto",
        status=ArmoryStatus.APPROVED,
    )
    seeded.add(row)
    seeded.commit()
    armory.invalidate()
    return row


@pytest.fixture
def carbine(seeded, cartridge):
    """The M1 Carbine, with the several makers that are the point of the table."""
    makers = [Manufacturer(name=name) for name in ("Inland", "Rock-Ola", "IBM")]
    seeded.add_all(makers)
    row = FirearmModel(
        name="M1 Carbine",
        aliases="US M1 Carbine\n.30 M1 Carbine",
        kind=FirearmKind.CARBINE,
        status=ArmoryStatus.APPROVED,
    )
    row.calibers = [cartridge]
    row.manufacturers = makers
    seeded.add(row)
    seeded.commit()
    armory.invalidate()
    return row


class TestOneCartridgeHoweverItIsWritten:
    @pytest.mark.parametrize(
        "spelling", [".32 ACP", "7.65mm Browning", "7.65x17mm", ".32 Auto", "  .32 acp  "]
    )
    def test_every_spelling_gives_the_canonical_name(self, seeded, cartridge, spelling):
        assert armory.canonical_caliber(seeded, spelling) == ".32 ACP"

    def test_an_unknown_one_is_not_invented(self, seeded, cartridge):
        assert armory.canonical_caliber(seeded, "9.3x62mm") is None

    def test_the_longest_spelling_wins(self, seeded):
        """ "7.62x54R" contains "7.62", and both are real spellings of
        something. Trying the longest first is the only thing that stops the
        rimmed Russian round being read as a bare 7.62."""
        seeded.add_all(
            [
                Caliber(name="7.62x54mmR", aliases="7.62x54R", status=ArmoryStatus.APPROVED),
                Caliber(name="7.62mm", aliases="7.62", status=ArmoryStatus.APPROVED),
            ]
        )
        seeded.commit()
        armory.invalidate()
        assert armory.canonical_caliber(seeded, "Mosin 7.62x54R rifle") == "7.62x54mmR"


class TestAModelHasSeveralMakers:
    def test_one_row_not_one_per_maker(self, seeded, carbine):
        """The whole reason for the join table. Nine firms built the M1
        Carbine and there must not be nine M1 Carbines."""
        rows = seeded.query(FirearmModel).filter(FirearmModel.name == "M1 Carbine").all()
        assert len(rows) == 1
        assert sorted(rows[0].manufacturer_names) == ["IBM", "Inland", "Rock-Ola"]

    def test_the_model_declines_to_pick_one_of_them(self, seeded, carbine):
        """A title naming none of the nine does not say which, so the honest
        answer about the maker is nothing at all."""
        assert armory.match(seeded, "US M1 Carbine, 1944").manufacturer is None

    def test_but_a_single_maker_is_simply_a_fact(self, seeded, cartridge):
        maker = Manufacturer(name="Springfield")
        seeded.add(maker)
        row = FirearmModel(name="M1 Garand", status=ArmoryStatus.APPROVED)
        row.manufacturers = [maker]
        seeded.add(row)
        seeded.commit()
        armory.invalidate()
        assert armory.match(seeded, "Excellent M1 Garand").manufacturer == "Springfield"


class TestNothingPendingDecidesAnything:
    def test_a_pending_caliber_normalizes_nothing(self, seeded):
        seeded.add(Caliber(name=".32 ACP", aliases="7.65mm Browning"))
        seeded.commit()
        armory.invalidate()
        assert armory.canonical_caliber(seeded, "7.65mm Browning") is None

    def test_a_pending_model_matches_nothing(self, seeded):
        seeded.add(FirearmModel(name="M1 Carbine", kind=FirearmKind.CARBINE))
        seeded.commit()
        armory.invalidate()
        assert armory.match(seeded, "US M1 Carbine").model is None

    def test_and_promoting_it_is_what_turns_it_on(self, seeded):
        row = FirearmModel(name="M1 Carbine", kind=FirearmKind.CARBINE)
        seeded.add(row)
        seeded.commit()
        armory.invalidate()
        assert armory.match(seeded, "M1 Carbine").model is None

        assert armory.promote(seeded, "models", [row.id])[0] == 1
        seeded.commit()
        assert armory.match(seeded, "M1 Carbine").model == "M1 Carbine"

    def test_sending_it_back_turns_it_off_again(self, seeded, carbine):
        assert armory.send_back(seeded, "models", [carbine.id])[0] == 1
        seeded.commit()
        assert armory.match(seeded, "M1 Carbine").model is None

    def test_promoting_what_is_already_promoted_changes_nothing(self, seeded, carbine):
        assert armory.promote(seeded, "models", [carbine.id])[0] == 0


class TestAModelMayHaveSeveralCalibers:
    """A Steyr M95 is 8x50mmR or 8x56mmR depending on when it was rebarreled,
    and both are right for a rifle sold today as "an M95"."""

    @pytest.fixture
    def m95(self, seeded):
        rounds = [
            Caliber(
                name="8x50mmR Mannlicher",
                aliases="8x50R Mannlicher",
                status=ArmoryStatus.APPROVED,
            ),
            Caliber(name="8x56mmR Hungarian", aliases="8x56R", status=ArmoryStatus.APPROVED),
        ]
        seeded.add_all(rounds)
        row = FirearmModel(name="Steyr M95", kind=FirearmKind.RIFLE, status=ArmoryStatus.APPROVED)
        row.calibers = rounds
        seeded.add(row)
        seeded.commit()
        armory.invalidate()
        return row

    def test_both_are_stored_on_the_one_row(self, seeded, m95):
        assert m95.caliber_names == ["8x50mmR Mannlicher", "8x56mmR Hungarian"]

    def test_with_several_it_declines_to_pick_one(self, seeded, m95):
        """The model does not know which this particular rifle is, and a guess
        dressed as a fact is worse than a blank."""
        assert armory.match(seeded, "Steyr M95 rifle").caliber is None
        assert armory.fill_in(seeded, "Steyr M95 rifle").caliber is None

    def test_but_a_listing_that_states_one_is_still_normalized(self, seeded, m95):
        found = armory.fill_in(seeded, "Steyr M95 rifle", caliber="8x56R")
        assert found.caliber == "8x56mmR Hungarian"

    def test_with_exactly_one_it_fills_the_blank(self, seeded, m95):
        m95.calibers = m95.calibers[:1]
        seeded.commit()
        armory.invalidate()
        assert armory.fill_in(seeded, "Steyr M95 rifle").caliber == "8x50mmR Mannlicher"


class TestFillingInWhatAListingDoesNotSay:
    def test_a_blank_caliber_comes_from_the_model(self, seeded, carbine):
        assert armory.fill_in(seeded, "US M1 Carbine, 1944").caliber == ".32 ACP"

    def test_a_stated_caliber_is_normalized_and_kept(self, seeded, carbine):
        """Normalizing is not overruling: the two spellings are one answer."""
        found = armory.fill_in(seeded, "US M1 Carbine", caliber="7.65mm Browning")
        assert found.caliber == ".32 ACP"

    def test_a_stated_caliber_the_model_disagrees_with_still_wins(self, seeded, carbine):
        """Sixty years of surplus is full of rebarreled guns, and the dealer
        has the thing in their hand."""
        found = armory.fill_in(seeded, "US M1 Carbine", caliber="9.3x62mm")
        assert found.caliber == "9.3x62mm"

    def test_the_kind_comes_across(self, seeded, carbine):
        assert armory.fill_in(seeded, "US M1 Carbine").kind is FirearmKind.CARBINE


class TestTheKindsMapOntoTheBrowseFilter:
    @pytest.mark.parametrize(
        "kind",
        [
            FirearmKind.PISTOL,
            FirearmKind.REVOLVER,
            FirearmKind.FLINTLOCK_PISTOL,
            FirearmKind.PERCUSSION_PISTOL,
            FirearmKind.PERCUSSION_REVOLVER,
        ],
    )
    def test_handguns(self, kind):
        assert kind.is_handgun and not kind.is_long_gun

    @pytest.mark.parametrize(
        "kind",
        [
            FirearmKind.RIFLE,
            FirearmKind.CARBINE,
            FirearmKind.SHOTGUN,
            FirearmKind.FLINTLOCK_RIFLE,
            FirearmKind.FLINTLOCK_CARBINE,
            FirearmKind.PERCUSSION_RIFLE,
            FirearmKind.PERCUSSION_CARBINE,
        ],
    )
    def test_long_guns(self, kind):
        assert kind.is_long_gun and not kind.is_handgun

    def test_a_carbine_is_not_a_rifle(self):
        """A Trapdoor Carbine and a Trapdoor Rifle are different guns, priced
        and collected separately."""
        assert FirearmKind.CARBINE is not FirearmKind.RIFLE


class TestDiscovery:
    def test_an_unexplained_name_is_written_down_once(self, seeded):
        first = armory.propose_model(seeded, "Vetterli-Vitali M1870/87", "Italian Vetterli")
        seeded.commit()
        again = armory.propose_model(seeded, "Vetterli-Vitali M1870/87", "Another Vetterli")
        seeded.commit()
        assert first is again
        assert first.status is ArmoryStatus.PENDING
        assert seeded.query(FirearmModel).count() == 1

    def test_the_titles_it_was_seen_in_are_kept(self, seeded):
        row = armory.propose_model(seeded, "Vetterli-Vitali", "First listing")
        seeded.commit()
        armory.propose_model(seeded, "Vetterli-Vitali", "Second listing")
        seeded.commit()
        assert row.first_seen_in.splitlines() == ["First listing", "Second listing"]

    def test_the_same_name_twice_without_a_commit_is_one_row(self, seeded):
        """The shape a scan produces, and the shape nothing tested.

        This session runs with autoflush off, so a row added and not flushed is
        invisible to the next lookup in it. Every test above commits between
        proposals; a scan meeting the same unknown cartridge in forty listings
        does not, and it added forty identical rows and died on the UNIQUE
        constraint at commit.
        """
        first = armory.propose_caliber(seeded, "8x57mm", "One rifle")
        again = armory.propose_caliber(seeded, "8x57mm", "Another rifle")
        seeded.commit()
        assert first is again
        assert seeded.query(Caliber).filter_by(name="8x57mm").count() == 1

    def test_and_the_same_holds_for_models_and_makers(self, seeded):
        armory.propose_model(seeded, "Model 1873", "One")
        armory.propose_model(seeded, "Model 1873", "Two")
        armory.propose_manufacturer(seeded, "Bernardelli", "One")
        armory.propose_manufacturer(seeded, "Bernardelli", "Two")
        seeded.commit()
        assert seeded.query(FirearmModel).filter_by(name="Model 1873").count() == 1
        assert seeded.query(Manufacturer).filter_by(name="Bernardelli").count() == 1

    def test_a_maker_the_registry_knows_is_not_proposed(self, seeded, carbine):
        """Including under one of its other spellings, which is the point."""
        maker = seeded.query(Manufacturer).filter_by(name="Inland").one()
        maker.aliases = "Inland Division"
        maker.status = ArmoryStatus.APPROVED
        seeded.commit()
        armory.invalidate()
        assert armory.propose_manufacturer(seeded, "Inland Division") is None

    def test_something_already_known_is_not_proposed(self, seeded, carbine):
        assert armory.propose_model(seeded, "US M1 Carbine") is None

    def test_nor_is_a_cartridge_known_under_another_name(self, seeded, cartridge):
        """The case that matters: a scan meeting "7.65mm Browning" for the
        hundredth time must not keep proposing it because the row it belongs
        to is called ".32 ACP"."""
        assert armory.propose_caliber(seeded, "7.65mm Browning") is None

    def test_the_pending_count_is_what_the_badge_shows(self, seeded):
        armory.propose_model(seeded, "Something Unknown", "A listing")
        armory.propose_caliber(seeded, "9.3x62mm", "A listing")
        seeded.commit()
        assert armory.pending_counts(seeded) == {
            "models": 1,
            "calibers": 1,
            "manufacturers": 0,
        }


class TestMerging:
    def test_mosin_becomes_an_alias_of_mosin_nagant(self, seeded):
        source = Manufacturer(name="Mosin")
        target = Manufacturer(name="Mosin-Nagant", aliases="Mosin Nagant")
        seeded.add_all([source, target])
        seeded.commit()

        armory.merge_manufacturers(seeded, source.id, target.id)
        seeded.commit()

        assert source.status is ArmoryStatus.MERGED
        assert source.merged_into_id == target.id
        # The source's own name has to survive as a spelling, or the merge
        # quietly stops recognizing the very text that prompted it.
        assert "Mosin" in target.spellings

    def test_a_merged_caliber_restamps_the_listings_that_carried_it(self, seeded):
        from app.models import Item, Site, utcnow

        site = seeded.query(Site).order_by(Site.id).first()
        listing = Item(
            site_id=site.id,
            external_key="mosin",
            url="https://example.test/mosin",
            title="Mosin-Nagant M91/30",
            caliber="7.62x54R",
            is_active=True,
            first_seen_at=utcnow(),
            last_seen_at=utcnow(),
        )
        source = Caliber(name="7.62x54R", status=ArmoryStatus.APPROVED)
        target = Caliber(name="7.62x54mmR", status=ArmoryStatus.APPROVED)
        seeded.add_all([listing, source, target])
        seeded.commit()

        moved = armory.merge_calibers(seeded, source.id, target.id)
        seeded.commit()
        assert moved == 1
        assert listing.caliber == "7.62x54mmR"

    def test_a_merged_caliber_moves_the_models_that_named_it(self, seeded, carbine, cartridge):
        target = Caliber(name=".32 Auto Cartridge", status=ArmoryStatus.APPROVED)
        seeded.add(target)
        seeded.commit()

        armory.merge_calibers(seeded, cartridge.id, target.id)
        seeded.commit()
        assert carbine.caliber_names == [".32 Auto Cartridge"]

    def test_a_merged_model_hands_over_its_makers(self, seeded, carbine):
        spare = FirearmModel(name="Carbine, Cal .30, M1", status=ArmoryStatus.APPROVED)
        spare.manufacturers = [Manufacturer(name="Underwood")]
        seeded.add(spare)
        seeded.commit()

        armory.merge_models(seeded, spare.id, carbine.id)
        seeded.commit()
        assert "Underwood" in carbine.manufacturer_names
        assert "Carbine, Cal .30, M1" in carbine.spellings

    def test_a_row_cannot_be_merged_into_itself(self, seeded, carbine):
        with pytest.raises(armory.MergeError):
            armory.merge_models(seeded, carbine.id, carbine.id)

    def test_nor_into_one_that_has_itself_been_merged_away(self, seeded):
        a, b, c = (Caliber(name=name) for name in (".30-06", ".30-06 Sprg", ".30-06 Springfield"))
        seeded.add_all([a, b, c])
        seeded.commit()
        armory.merge_calibers(seeded, b.id, c.id)
        seeded.commit()
        with pytest.raises(armory.MergeError):
            armory.merge_calibers(seeded, a.id, b.id)


class TestTheShippedCatalogFile:
    def test_it_seeds_everything_awaiting_approval(self, seeded):
        """Nothing in the file has been checked by whoever runs this site."""
        report = armory.seed(seeded)
        seeded.commit()
        assert report.total > 0
        assert not (
            seeded.query(FirearmModel).filter(FirearmModel.status != ArmoryStatus.PENDING).count()
        )

    def test_running_it_twice_adds_nothing(self, seeded):
        armory.seed(seeded)
        seeded.commit()
        assert armory.seed(seeded).total == 0

    def test_it_does_not_undo_an_admin(self, seeded):
        """An approval, an edit and a disabling all survive a re-seed. They are
        real data; the file is a starting point."""
        armory.seed(seeded)
        seeded.commit()
        garand = seeded.query(FirearmModel).filter_by(name="M1 Garand").one()
        garand.status = ArmoryStatus.APPROVED
        garand.notes = "Checked."
        carbine = seeded.query(FirearmModel).filter_by(name="M1 Carbine").one()
        carbine.enabled = False
        seeded.commit()

        armory.seed(seeded)
        seeded.commit()
        assert garand.status is ArmoryStatus.APPROVED
        assert garand.notes == "Checked."
        assert carbine.enabled is False

    def test_but_a_deleted_row_does_come_back_as_pending(self, seeded):
        """Worth pinning down, because it surprises people. "Missing" and
        "deleted" look the same to an additive seed, so deleting is not how a
        row gets rejected -- leaving it pending or disabling it is, and both
        of those survive.
        """
        armory.seed(seeded)
        seeded.commit()
        seeded.delete(seeded.query(FirearmModel).filter_by(name="M1 Carbine").one())
        seeded.commit()

        armory.seed(seeded)
        seeded.commit()
        back = seeded.query(FirearmModel).filter_by(name="M1 Carbine").one()
        assert back.status is ArmoryStatus.PENDING


class TestTheExporterCarriesEveryColumn:
    """Checked against the table definition, not against a list kept by hand.

    `Manufacturer.country` was added and the exporter was not told about it, so
    `armory export` wrote a curated armory out with every firm's country
    stripped -- 81 of 99 rows -- and the round-trip test below passed anyway,
    because it compares through `plan_sync` and a sync does not look at that
    field either. The failure was silent in both directions: the file looked
    fine, and so did the database it came from.

    Enumerating the columns is what makes the next one fail here instead. A
    column that genuinely should not travel goes in the skip list below, with
    its reason -- a decision somebody writes down, rather than one that can
    happen by forgetting.

    The row is built with every field set to something *non-default*, because
    the exporter drops blanks: a field left at its default never appears in the
    file whether the exporter knows about it or not.
    """

    #: Columns that deliberately do not go into the file, and why.
    NOT_EXPORTED = {
        "id",  # a surrogate key; the name is the identity in the file
        "created_at",
        "updated_at",
        "merged_into_id",  # a local row id, meaningless in another database
        "first_seen_in",  # which listings *here* proposed it: provenance, not knowledge
        # What a merge in *this* database took, so its undo can give it back.
        # It holds local row ids and is a record of edits made here rather than
        # anything the armory knows about guns.
        "merge_undo",
    }

    #: What the file calls a column, where the two differ.
    RENAMED = {"wikipedia_url": "wikipedia"}

    def _assert_every_column_travels(self, table, row, exported, section):
        written = next(entry for entry in exported[section] if entry["name"] == row.name)
        for column in table.__table__.columns:
            if column.name in self.NOT_EXPORTED:
                continue
            expected = self.RENAMED.get(column.name, column.name)
            assert expected in written, (
                f"{table.__name__}.{column.name} never reaches the file. Either export "
                f"it, or add it to NOT_EXPORTED with the reason -- an export that drops "
                f"a column strips it out of every armory that file is carried to."
            )

    def test_a_manufacturer(self, clean_db):
        row = Manufacturer(
            name="Everything Works",
            aliases="EW",
            country="Belgium",
            notes="a note",
            position=42,
            enabled=False,
            status=ArmoryStatus.APPROVED,
        )
        clean_db.add(row)
        clean_db.commit()
        self._assert_every_column_travels(
            Manufacturer, row, armory.export_armory(clean_db), "manufacturers"
        )

    def test_a_caliber(self, clean_db):
        row = Caliber(
            name="9x99mm Everything",
            aliases="9x99",
            notes="a note",
            enabled=False,
            status=ArmoryStatus.APPROVED,
        )
        clean_db.add(row)
        clean_db.commit()
        self._assert_every_column_travels(Caliber, row, armory.export_armory(clean_db), "calibers")

    def test_a_model(self, clean_db):
        maker = Manufacturer(name="Everything Works", status=ArmoryStatus.APPROVED)
        cartridge = Caliber(name="9x99mm Everything", status=ArmoryStatus.APPROVED)
        clean_db.add_all([maker, cartridge])
        clean_db.flush()
        row = FirearmModel(
            name="Everything Model 1",
            aliases="EM1",
            kind=FirearmKind.RIFLE,
            country="Belgium",
            wikipedia_url="https://example.invalid/em1",
            notes="a note",
            position=42,
            enabled=False,
            status=ArmoryStatus.APPROVED,
        )
        row.manufacturers = [maker]
        row.calibers = [cartridge]
        clean_db.add(row)
        clean_db.commit()
        self._assert_every_column_travels(
            FirearmModel, row, armory.export_armory(clean_db), "models"
        )

    def test_a_maker_country_makes_the_trip_by_value(self, clean_db, tmp_path):
        """The specific field that was lost, pinned by value rather than by the
        presence of a key."""
        clean_db.add(Manufacturer(name="Mauser", country="Germany"))
        clean_db.commit()

        path = tmp_path / "catalog.yaml"
        armory.write_export(clean_db, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        row = next(m for m in written["manufacturers"] if m["name"] == "Mauser")
        assert row["country"] == "Germany"


class TestTheRoundTripToAFlatFile:
    def test_export_then_sync_is_a_no_op(self, seeded, tmp_path):
        """The strongest thing to say about the format: everything that
        matters survives the trip, so a sync against a fresh export finds
        nothing to do."""
        armory.seed(seeded)
        seeded.commit()
        path = tmp_path / "catalog.yaml"
        armory.write_export(seeded, path)
        assert not armory.plan_sync(seeded, path)

    def test_statuses_travel_with_it(self, seeded, tmp_path):
        """A row promoted here should arrive as production there, or every
        export would be a demotion."""
        armory.seed(seeded)
        seeded.commit()
        garand = seeded.query(FirearmModel).filter_by(name="M1 Garand").one()
        armory.promote(seeded, "models", [garand.id])
        seeded.commit()

        path = tmp_path / "catalog.yaml"
        armory.write_export(seeded, path)
        assert "status: approved" in path.read_text()

    def test_a_plan_names_the_fields_that_differ(self, seeded, tmp_path):
        import yaml

        armory.seed(seeded)
        seeded.commit()
        path = tmp_path / "catalog.yaml"
        armory.write_export(seeded, path)
        data = yaml.safe_load(path.read_text())
        for entry in data["models"]:
            if entry["name"] == "M1 Garand":
                entry["status"] = "approved"
                entry["notes"] = "Checked."
        path.write_text(yaml.safe_dump(data))

        plan = armory.plan_sync(seeded, path)
        change = next(c for c in plan.models if c.name == "M1 Garand")
        assert change.action == "update"
        assert change.fields == ["notes", "status"]

    def test_sync_applies_adds_and_updates(self, seeded, tmp_path):
        import yaml

        path = tmp_path / "catalog.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "calibers": [{"name": ".45-70 Government", "status": "approved"}],
                    "models": [
                        {
                            "name": "Model 1873 Trapdoor Carbine",
                            "kind": "carbine",
                            "caliber": ".45-70 Government",
                            "status": "approved",
                        }
                    ],
                }
            )
        )
        done = armory.apply_sync(seeded, path)
        seeded.commit()
        assert done["added"] == 2
        found = armory.match(seeded, "Springfield Model 1873 Trapdoor Carbine")
        assert found.kind is FirearmKind.CARBINE
        assert found.caliber == ".45-70 Government"

    def test_it_will_not_delete_without_being_asked(self, seeded, tmp_path):
        """An armory is curated in two places, and a row missing from the file
        is more often unexported than unwanted."""
        import yaml

        seeded.add(Caliber(name="Something Local", status=ArmoryStatus.APPROVED))
        seeded.commit()
        path = tmp_path / "catalog.yaml"
        path.write_text(yaml.safe_dump({"calibers": [], "models": []}))

        assert armory.apply_sync(seeded, path)["deleted"] == 0
        seeded.commit()
        assert seeded.query(Caliber).filter_by(name="Something Local").count() == 1

        assert armory.apply_sync(seeded, path, prune=True)["deleted"] == 1
        seeded.commit()
        assert seeded.query(Caliber).filter_by(name="Something Local").count() == 0


class TestTheTwoCachesStayInStep:
    """The maker rules are built partly from the armory now.

    A model with exactly one maker names that maker, so promoting a model,
    changing its makers or approving a firm all change what the maker matcher
    will say. The two registries are separate caches, and leaving one of them
    alone produced the worst kind of bug: promoting "Inland" and then finding
    that "Inland M1 Carbine" still had no maker, with nothing on screen to
    explain why.
    """

    def test_promoting_a_maker_takes_effect_at_once(self, seeded):
        from app.services import manufacturers

        maker = Manufacturer(name="Inland", status=ArmoryStatus.PENDING)
        seeded.add(maker)
        seeded.commit()
        manufacturers.invalidate()
        assert manufacturers.extract(seeded, "Inland M1 Carbine") is None

        armory.promote(seeded, "manufacturers", [maker.id])
        seeded.commit()
        assert manufacturers.extract(seeded, "Inland M1 Carbine") == "Inland"

    def test_promoting_a_model_takes_effect_at_once(self, seeded):
        from app.services import manufacturers

        maker = Manufacturer(name="Rock-Ola")
        model = FirearmModel(name="M1 Carbine", status=ArmoryStatus.PENDING)
        seeded.add_all([maker, model])
        model.manufacturers.append(maker)
        seeded.commit()
        manufacturers.invalidate()
        assert manufacturers.extract(seeded, "A US M1 Carbine") is None

        armory.promote(seeded, "models", [model.id])
        seeded.commit()
        assert manufacturers.extract(seeded, "A US M1 Carbine") == "Rock-Ola"


class TestSeedingTheManufacturers:
    def test_the_file_brings_its_own_makers(self, seeded):
        """The M1 Carbine's nine were dropped on the floor before this: the
        seeder skipped any maker the table did not already have, so the model
        arrived with one of them."""
        armory.seed(seeded)
        seeded.commit()
        carbine = seeded.query(FirearmModel).filter_by(name="M1 Carbine").one()
        assert len(carbine.manufacturers) == 9
        assert "Rock-Ola" in carbine.manufacturer_names
        assert "IBM" in carbine.manufacturer_names

    def test_an_m1_garand_has_all_four_of_its_makers(self, seeded):
        armory.seed(seeded)
        seeded.commit()
        garand = seeded.query(FirearmModel).filter_by(name="M1 Garand").one()
        assert sorted(garand.manufacturer_names) == [
            "Harrington & Richardson",
            "International Harvester",
            "Springfield",
            "Winchester",
        ]

    def test_they_arrive_awaiting_approval_too(self, seeded):
        armory.seed(seeded)
        seeded.commit()
        added = seeded.query(Manufacturer).filter_by(name="Rock-Ola").one()
        assert added.status is ArmoryStatus.PENDING

    def test_and_a_pending_maker_decides_nothing(self, seeded):
        from app.services import manufacturers

        armory.seed(seeded)
        seeded.commit()
        assert manufacturers.extract(seeded, "Rock-Ola M1 Carbine") is None


class TestTheRoundTripIsStable:
    """Export, sync, and find nothing to do. Every time.

    An unstable round trip is worse than no round trip: a sync that always
    reports work makes the plan meaningless, and there is no way to tell a
    real difference from the noise.
    """

    def test_an_empty_note_does_not_look_like_a_change(self, seeded, tmp_path):
        """A blank textarea stored "", the export dropped it as blank, and
        reading it back gave None -- so a fresh export reported two rows to
        update, forever, and applying it changed nothing."""
        armory.seed(seeded)
        seeded.commit()
        row = seeded.query(FirearmModel).filter_by(name="Walther PP").one()
        row.notes = ""
        row.aliases = row.aliases or ""
        seeded.commit()

        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)
        assert not armory.plan_sync(seeded, path)

    def test_the_manufacturers_go_out_with_it(self, seeded, tmp_path):
        """They were missed at first, so a curated armory could be committed
        with its models and calibers and silently without the firms."""
        armory.seed(seeded)
        seeded.commit()
        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)

        import yaml

        written = yaml.safe_load(path.read_text())
        names = {row["name"] for row in written["manufacturers"]}
        assert "Rock-Ola" in names
        assert "International Harvester" in names

    def test_and_come_back_with_their_spellings(self, seeded, tmp_path):
        armory.seed(seeded)
        seeded.commit()
        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)

        for row in seeded.query(Manufacturer).all():
            seeded.delete(row)
        seeded.commit()

        done = armory.apply_sync(seeded, path)
        seeded.commit()
        assert done["added"] > 0
        restored = seeded.query(Manufacturer).filter_by(name="Rock-Ola").one()
        assert "Rock Ola" in restored.spellings


class TestAModelDesignationIsNotUnique:
    """ "Model 1911" is a Colt automatic and a Schmidt-Rubin rifle.

    So is "Model 1917" (a Colt revolver, an Enfield rifle), "Model 1903" (a
    Springfield rifle, a Smith & Wesson revolver) and "Model 1873" (a
    Winchester, a Colt, a Springfield Trapdoor). Left alone, the armory filed
    a $2,000 revolver under rifles, in .30-06, made by Winchester.
    """

    @pytest.fixture
    def enfield(self, seeded):
        row = FirearmModel(
            name="M1917 Enfield",
            aliases="Model 1917\nUS M1917",
            kind=FirearmKind.RIFLE,
            status=ArmoryStatus.APPROVED,
        )
        cartridge = Caliber(name=".30-06 Springfield", status=ArmoryStatus.APPROVED)
        seeded.add_all([row, cartridge])
        row.calibers = [cartridge]
        seeded.commit()
        armory.invalidate()
        return row

    def test_a_title_that_plainly_says_otherwise_discards_the_match(self, seeded, enfield):
        """The whole match, not just its kind: a model wrong about what kind
        of gun this is was not this gun, so its caliber is wrong too."""
        found = armory.match(seeded, "COLT MODEL 1917 REVOLVER Gunsmith special, .45 ACP")
        assert found.model is None
        assert found.caliber is None

    def test_and_the_stated_caliber_is_left_alone(self, seeded, enfield):
        found = armory.fill_in(seeded, "COLT MODEL 1917 REVOLVER, .45 ACP", caliber=".45 ACP")
        assert found.caliber == ".45 ACP"

    def test_a_title_that_agrees_still_matches(self, seeded, enfield):
        found = armory.match(seeded, "US M1917 Enfield rifle .30-06")
        assert found.model == "M1917 Enfield"

    def test_a_title_that_says_nothing_either_way_still_matches(self, seeded, enfield):
        """Silence is not disagreement."""
        assert armory.match(seeded, "US M1917, 1918 production").model == "M1917 Enfield"


class TestTheNounsOutrankTheDesignations:
    """RIFLE_PATTERNS and PISTOL_PATTERNS carry model designations as well as
    nouns, and the designation is the thing in dispute. Reading both lists
    equally made "COLT MODEL 1917 REVOLVER" ambiguous -- rifle by "model
    1917", handgun by "revolver" -- when it could hardly be plainer."""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("COLT MODEL 1917 REVOLVER Gunsmith special", "handgun"),
            ("Factory-Nickeled S&W Model 1903 2nd Change Revolver", "handgun"),
            ("Awesome Armi San Marco Model 1873 Revolver", "handgun"),
            ("CZ 52 SEMI AUTO ASSAULT RIFLES", "rifle"),
            ("Awesome Iver Johnson 1911A1 Carbine 16in Barrel", "rifle"),
            # No noun at all, so the fuller vocabulary answers instead.
            ("Schmidt Rubin Model 1911 with Matching Bayonet", "rifle"),
            # Neither, and nothing else settles it.
            ("Original U.S. WWII Leather Sling", None),
        ],
    )
    def test_what_the_title_plainly_says(self, title, expected):
        from app.services import classify

        assert classify.stated_kind(title) == expected


class TestTheKindRefinesRatherThanPromotes:
    """The armory knows what a model is. It does not know whether a listing is
    selling one -- "W+F Bern K31 Pioneer Sawback Bayonet" names a carbine and
    is a bayonet, and "Berthier 1907/15 and M16 bolt assembly" names a rifle
    and is a bag of parts. The accessory rules decide that question."""

    def test_an_accessory_naming_a_model_is_still_an_accessory(self, seeded):
        row = FirearmModel(
            name="Schmidt-Rubin K31",
            aliases="K31",
            kind=FirearmKind.CARBINE,
            status=ArmoryStatus.APPROVED,
        )
        seeded.add(row)
        seeded.commit()
        armory.invalidate()

        # The armory does match it -- that much is true, it is a K31 bayonet.
        assert armory.match(seeded, "W+F Bern K31 Pioneer Sawback Bayonet").model
        # And classify still says the listing is a bayonet, which is what the
        # scan and the reclassify path both defer to.
        derived = classify.enrich("W+F Bern K31 Pioneer Sawback Bayonet", None, 250.0)
        assert derived["is_bayonet"]
        assert not derived["is_rifle"]


class TestTheShippedFileIsActuallyShipped:
    """It has to be in the repository, not merely on the machine that wrote it.

    This is here because it was not, for a while. The file sat in
    backend/app/data/, and this repository's .gitignore carries an unanchored
    ``data/`` that matches a directory of that name at any depth -- so it was
    never committed, everything passed locally, and CI failed twelve tests
    with a FileNotFoundError that said nothing about the cause.

    One assertion that names the problem beats twelve that describe symptoms.
    """

    def test_the_seed_file_exists_where_the_code_expects_it(self):
        assert armory.SEED_FILE.is_file(), (
            f"{armory.SEED_FILE} is missing. If it exists on your machine but not in "
            "CI, check .gitignore: an unanchored 'data/' matches a directory of that "
            "name at any depth."
        )

    def test_it_is_not_inside_a_directory_the_repository_ignores(self):
        ignored = {"data", "dist", "node_modules", "__pycache__"}
        offending = ignored.intersection(part.lower() for part in armory.SEED_FILE.parts)
        assert not offending, (
            f"The shipped armory sits under {offending}, which .gitignore excludes. "
            "It would not reach a fresh checkout."
        )

    def test_and_it_parses(self):
        import yaml

        data = yaml.safe_load(armory.SEED_FILE.read_text(encoding="utf-8"))
        assert data["manufacturers"] and data["calibers"] and data["models"]


class TestAModelIsNamedInTheTitleOrNotAtAll:
    """The description is not read for models, unlike for makers.

    A maker's name in the prose is usually still the maker. A model
    designation in the prose is very often a comparison: a CZ vz.50 is
    described as a Walther PP copy, and a box of .32 ACP lists the pistols it
    suits. Reading those gave sixty-three listings the Walther PP as their
    model -- a third of them CZs, one of them ammunition -- and each would then
    have taken the PP's caliber and kind.
    """

    @pytest.fixture
    def walther(self, seeded):
        row = FirearmModel(
            name="Walther PP",
            kind=FirearmKind.PISTOL,
            status=ArmoryStatus.APPROVED,
        )
        seeded.add(row)
        seeded.commit()
        armory.invalidate()
        return row

    def test_the_title_names_it(self, seeded, walther):
        assert armory.match(seeded, "Waffen Walther PP Rig").model == "Walther PP"

    def test_a_mention_in_the_prose_does_not(self, seeded, walther):
        found = armory.match(
            seeded,
            "CZ vz.50 .32 ACP Czech Police Surplus Pistol",
            "The vz.50 is a close copy of the Walther PP, in the same calibre.",
        )
        assert found.model is None

    def test_nor_does_a_box_of_ammunition_listing_what_it_suits(self, seeded, walther):
        found = armory.match(
            seeded,
            "Czech .32 ACP/7.65 Browning 73 Grain FMJ Brass Case Ammo",
            "Suits the Walther PP, CZ 50 and other .32 ACP pistols.",
        )
        assert found.model is None


class TestAListingRemembersItsModel:
    def test_the_match_carries_the_row_id(self, seeded):
        row = FirearmModel(name="M1 Garand", status=ArmoryStatus.APPROVED)
        seeded.add(row)
        seeded.commit()
        armory.invalidate()

        found = armory.match(seeded, "Excellent M1 Garand - 1943 mfg")
        assert found.model_id == row.id

    def test_and_nothing_when_nothing_matched(self, seeded):
        assert armory.match(seeded, "A leather sling").model_id is None


class TestACountryOfOrigin:
    """Where the pattern comes from, filled into listings that do not say.

    The classifier reads a country out of a title -- "RUSSIAN M44 CARBINES"
    is Russia, "SWEDISH MAUSER M96" is Sweden -- and a great many titles name
    none. "M1 GARANDS, EXC" is one, and until the armory carried this those
    listings had no country at all and the browse filter had no opinion about
    them.
    """

    @pytest.fixture
    def american(self, seeded, carbine):
        carbine.country = "United States"
        seeded.commit()
        armory.invalidate()
        return carbine

    def test_the_model_supplies_it(self, seeded, american):
        assert armory.fill_in(seeded, "US M1 Carbine, 1944").country == "United States"

    def test_a_model_with_none_says_nothing(self, seeded, carbine):
        assert armory.fill_in(seeded, "US M1 Carbine").country is None

    def test_a_pending_model_supplies_nothing(self, seeded, american):
        """The same gate as everything else here."""
        american.status = ArmoryStatus.PENDING
        seeded.commit()
        armory.invalidate()
        assert armory.fill_in(seeded, "US M1 Carbine").country is None

    def test_it_is_stated_even_when_the_maker_cannot_be(self, seeded, american):
        """Unlike the maker, this is never a choice. Nine firms built the M1
        Carbine, so a title naming none of them leaves the maker unanswerable
        -- and all nine of them built an American carbine."""
        found = armory.fill_in(seeded, "US M1 Carbine")
        assert found.manufacturer is None
        assert found.country == "United States"

    def test_a_match_carrying_only_a_country_is_still_a_match(self, seeded):
        assert bool(armory.Match(country="Sweden"))

    def test_it_survives_the_round_trip_to_a_file(self, seeded, american, tmp_path):
        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)
        assert "country: United States" in path.read_text(encoding="utf-8")
        plan = armory.plan_sync(seeded, path)
        assert not plan

    def test_changing_it_in_the_file_is_reported_as_a_difference(self, seeded, american, tmp_path):
        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)
        path.write_text(
            path.read_text(encoding="utf-8").replace("country: United States", "country: Sweden"),
            encoding="utf-8",
        )
        change = next(c for c in armory.plan_sync(seeded, path).models if c.name == "M1 Carbine")
        assert change.fields == ["country"]

    def test_and_applying_it_writes_it(self, seeded, american, tmp_path):
        path = tmp_path / "armory.yaml"
        armory.write_export(seeded, path)
        path.write_text(
            path.read_text(encoding="utf-8").replace("country: United States", "country: Sweden"),
            encoding="utf-8",
        )
        armory.apply_sync(seeded, path)
        seeded.commit()
        assert seeded.query(FirearmModel).filter_by(name="M1 Carbine").one().country == "Sweden"


class TestAMergeCarriesTheCountry:
    def test_the_survivor_gains_it(self, seeded):
        """Added when the column was and missed in merge_models, which would
        have dropped the one fact the folded-away row was carrying."""
        keep = FirearmModel(name="Mosin-Nagant M91/30", status=ArmoryStatus.APPROVED)
        gone = FirearmModel(name="M91/30", country="Russia", status=ArmoryStatus.APPROVED)
        seeded.add_all([keep, gone])
        seeded.commit()
        armory.merge_models(seeded, gone.id, keep.id)
        seeded.commit()
        assert keep.country == "Russia"

    def test_but_it_does_not_overwrite_one(self, seeded):
        keep = FirearmModel(name="Karabiner 98k", country="Germany", status=ArmoryStatus.APPROVED)
        gone = FirearmModel(name="K98k", country="Portugal", status=ArmoryStatus.APPROVED)
        seeded.add_all([keep, gone])
        seeded.commit()
        armory.merge_models(seeded, gone.id, keep.id)
        seeded.commit()
        assert keep.country == "Germany"


class TestTheShippedFileNamesItsCountries:
    """Every model in the shipped armory says where its pattern comes from,
    and says it the way the classifier says it.

    Both matter. A blank means a listing that names no country stays blank,
    which is the case this exists for. A spelling the classifier never
    produces -- "USSR" against titles read as "Russia" -- is worse than a
    blank: it splits one country into two filters that each show half the
    rifles.
    """

    @pytest.fixture
    def entries(self):
        import yaml

        return yaml.safe_load(armory.SEED_FILE.read_text(encoding="utf-8"))["models"]

    def test_every_curated_model_has_one(self, entries):
        """A model somebody has looked at names its country.

        Stated as "has a kind" rather than "is in the file", and that is the
        whole point of the wording. The file is no longer only the hand-written
        baseline: discovery proposes designations from listings, so it now
        carries hundreds of rows that are a name and nothing else. Demanding a
        country on those would fail this suite until somebody had worked
        through every one of them, which is a test holding the build hostage to
        a curation backlog.

        A kind is the marker of a row somebody has actually judged -- it cannot
        be guessed from a title -- and every model carrying one carries a
        country too. So the invariant maintains itself: curate a discovered row
        far enough to say it is a carbine, and this asks where it is from.
        """
        judged = [
            entry for entry in entries if entry.get("kind") and entry.get("status") != "merged"
        ]
        assert judged, "no curated models in the file at all -- has it been overwritten?"
        assert [entry["name"] for entry in judged if not entry.get("country")] == []

    def test_every_one_is_a_country_the_classifier_can_produce(self, entries):
        known = {country for _pattern, country in classify.COUNTRY_PATTERNS}
        named = {entry["country"] for entry in entries if entry.get("country")}
        assert named <= known, f"not spelled the way the classifier spells them: {named - known}"

    def test_the_seeder_carries_it_across(self, seeded):
        armory.seed(seeded)
        seeded.commit()
        garand = seeded.query(FirearmModel).filter_by(name="M1 Garand").one()
        assert garand.country == "United States"


class TestACaliberCanBeSwitchedOff:
    """The column added in migration 0018, and why it exists.

    Three tables behaved three ways. A model or a maker could be disabled --
    kept, taken out of matching, and left where a scan will find it and stop
    proposing the name again. A caliber could not, so its only durable "no" was
    "send back for approval", which is the same mechanism wearing a name that
    reads like an undo rather than a decision.

    Deleting is not the answer for any of the three: every ``propose_*`` looks
    a name up regardless of status, so a surviving row is what suppresses
    re-proposal and a deleted one comes back the next time a title names it.
    """

    def test_a_disabled_caliber_stops_matching(self, clean_db):
        row = Caliber(name="9x99mm Nonsense", status=ArmoryStatus.APPROVED)
        clean_db.add(row)
        clean_db.commit()
        armory.invalidate()
        assert armory.canonical_caliber(clean_db, "a 9x99mm Nonsense rifle") == "9x99mm Nonsense"

        row.enabled = False
        clean_db.commit()
        armory.invalidate()
        assert armory.canonical_caliber(clean_db, "a 9x99mm Nonsense rifle") is None

    def test_but_it_still_stops_a_scan_proposing_the_name(self, clean_db):
        """The whole point of disabling rather than deleting."""
        row = Caliber(name="9x99mm Nonsense", status=ArmoryStatus.APPROVED, enabled=False)
        clean_db.add(row)
        clean_db.commit()
        armory.invalidate()

        assert armory.propose_caliber(clean_db, "9x99mm Nonsense") is row
        assert (
            clean_db.query(Caliber).filter_by(name="9x99mm Nonsense").count() == 1
        ), "a second row was created, so the name is being asked about again"

    def test_it_survives_the_trip_through_a_file(self, clean_db, tmp_path):
        clean_db.add(Caliber(name="9x99mm Nonsense", status=ArmoryStatus.APPROVED, enabled=False))
        clean_db.commit()

        path = tmp_path / "catalog.yaml"
        armory.write_export(clean_db, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        row = next(c for c in written["calibers"] if c["name"] == "9x99mm Nonsense")
        assert row["enabled"] is False

    def test_and_comes_back_off_when_seeded_somewhere_else(self, clean_db, tmp_path):
        clean_db.add(Caliber(name="9x99mm Nonsense", status=ArmoryStatus.APPROVED, enabled=False))
        clean_db.commit()
        path = tmp_path / "catalog.yaml"
        armory.write_export(clean_db, path)

        clean_db.query(Caliber).delete()
        clean_db.commit()
        armory.seed(clean_db, path)
        clean_db.commit()

        assert clean_db.query(Caliber).filter_by(name="9x99mm Nonsense").one().enabled is False


class TestAnEditWritesThroughToTheListings:
    """The armory used to change what it *would* say and nothing else.

    Promoting a model set a status and stopped, so every listing it now
    explained kept saying it matched nothing until the next scan or a hand-run
    `reclassify`. An admin who approved a row and looked at a listing saw no
    effect and had no way to tell a working change from a no-op -- which is
    exactly how a Smith & Wesson M&P40 came to be approved while the M&P40
    listing beside it still said it matched no model.

    Manufacturers have re-derived their listings since they existed. This is
    models and calibers catching up.
    """

    @pytest.fixture
    def shelf(self, clean_db):
        from app.models import Item, Site

        site = Site(slug="s", name="S", base_url="https://s.test/")
        clean_db.add(site)
        clean_db.flush()
        for n, title in enumerate(
            ("A Glock 22 Gen 4 pistol", "Another Glock 22", "Something else entirely")
        ):
            clean_db.add(
                Item(
                    site_id=site.id,
                    external_key=f"k{n}",
                    url="https://s.test/x",
                    title=title,
                )
            )
        clean_db.commit()
        return clean_db

    def _model(self, session, status=ArmoryStatus.PENDING):
        row = FirearmModel(name="Glock 22", status=status)
        session.add(row)
        session.commit()
        armory.invalidate()
        return row

    def test_promoting_links_the_listings_it_now_explains(self, shelf):
        from app.models import Item

        row = self._model(shelf)
        moved, touched = armory.promote(shelf, "models", [row.id])
        shelf.commit()

        assert (moved, touched) == (1, 2)
        linked = shelf.query(Item).filter(Item.firearm_model_id == row.id).count()
        assert linked == 2

    def test_and_says_how_many_so_a_no_op_is_visible(self, shelf):
        """The number is the point: without it, an admin cannot tell a change
        that worked from one that did nothing."""
        row = self._model(shelf, status=ArmoryStatus.APPROVED)
        assert armory.promote(shelf, "models", [row.id]) == (0, 0)

    def test_sending_one_back_lets_the_listings_go(self, shelf):
        from app.models import Item

        row = self._model(shelf)
        armory.promote(shelf, "models", [row.id])
        shelf.commit()

        moved, touched = armory.send_back(shelf, "models", [row.id])
        shelf.commit()

        assert (moved, touched) == (1, 2)
        assert shelf.query(Item).filter(Item.firearm_model_id.is_not(None)).count() == 0

    def test_disabling_one_lets_them_go_too(self, shelf):
        """The case that left twenty-nine listings pointing at four rows
        somebody had switched off."""
        from app.models import Item

        row = self._model(shelf)
        armory.promote(shelf, "models", [row.id])
        shelf.commit()

        row.enabled = False
        shelf.flush()
        armory.invalidate()
        assert armory.reprocess(shelf, row.spellings) == 2
        shelf.commit()
        assert shelf.query(Item).filter(Item.firearm_model_id.is_not(None)).count() == 0

    def test_it_only_visits_listings_the_change_could_reach(self, shelf):
        """Scoped rather than exhaustive: re-running the whole catalog on every
        edit would be correct and slow. A listing whose text contains none of
        the spellings involved cannot have changed its answer."""
        row = self._model(shelf)
        _moved, touched = armory.promote(shelf, "models", [row.id])
        # Two Glocks, not the third listing.
        assert touched == 2

    def test_a_maker_is_left_to_its_own_path(self, clean_db):
        """Manufacturers already re-derive their listings, in
        api/manufacturers.py. Doing it here as well would be a second copy of
        one decision, which is the mistake this codebase has made twice."""
        row = Manufacturer(name="Glock", status=ArmoryStatus.PENDING)
        clean_db.add(row)
        clean_db.commit()
        assert armory.promote(clean_db, "manufacturers", [row.id]) == (1, 0)
