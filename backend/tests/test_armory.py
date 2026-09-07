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

from app.models import ArmoryStatus, Caliber, FirearmKind, FirearmModel, Manufacturer
from app.services import armory


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

        assert armory.promote(seeded, "models", [row.id]) == 1
        seeded.commit()
        assert armory.match(seeded, "M1 Carbine").model == "M1 Carbine"

    def test_sending_it_back_turns_it_off_again(self, seeded, carbine):
        assert armory.send_back(seeded, "models", [carbine.id]) == 1
        seeded.commit()
        assert armory.match(seeded, "M1 Carbine").model is None

    def test_promoting_what_is_already_promoted_changes_nothing(self, seeded, carbine):
        assert armory.promote(seeded, "models", [carbine.id]) == 0


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
