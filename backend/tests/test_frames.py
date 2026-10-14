"""A handgun's frame size (app.services.frames).

Asked for on 2026-10-14. The phrases are production's, from its 8,545 pistols
and revolvers and its 605 variant labels measured that day; each exclusion is
a sentence the first draft misread.
"""

from __future__ import annotations

import pytest
import yaml

from app.models import ArmoryStatus, FirearmModel, Item, ModelVariant, Site
from app.services import armory, frames, variants


def size(title, description=None, *, revolver=False):
    return frames.read(title, description, revolver=revolver)[0]


class TestAPistolsSize:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("SIG P320 Full size 9mm Night Sites 1 MAG USED", "Full size"),
            ("BERETTA 92X RDO COMPACT PRE OWNED (1143686)", "Compact"),
            ("WALTHER PDP FS PRE OWNED (1143527)", "Full size"),
            ("Glock G43X Sub-Compact Pistol, 9mm, (1) 10rd Magazine", "Subcompact"),
            ("Beretta PX4 Storm Sub Compact 9mm Pistol", "Subcompact"),
            ("Canik METE MC9 9mm Semi Auto Micro Compact Pistol - Blem", "Micro"),
            ("ANIB Gen 3 Glock 35 - Long Slide", "Long slide"),
            ("PD Trade | FN FNS-40 Longslide | 40 S&W", "Long slide"),
            ("Colt 1911A1 Government Model 45ACP Made in 1971", "Full size"),
            ("COLT COMBAT COMMANDER PRE OWNED (1142406)", "Compact"),
            ('Tisas USA 1911A1 Tank Commander 9mm Luger 4.25"', "Compact"),
            ("KIMBER MICRO 9 PRE OWNED (1138306)", "Micro"),
        ],
    )
    def test_a_titles_size_is_the_versions_name(self, title, expected):
        assert size(title) == expected

    def test_a_long_slide_is_the_longer_slide_not_full_size(self):
        assert size("Glock 34 Gen 4 Full-Size Long Slide 9mm") == "Long slide"
        # In a description's prose it is an adjective, and left to the armory.
        assert size("Glock 34", "The Glock 34 is a full-size long-slide handgun") is None

    @pytest.mark.parametrize(
        "description",
        [
            "The Walther PP 32ACP Browning Pistol is a compact and reliable firearm",
            "but in a more compact and lighter weight pistol.",
            "Compact and rugged, the Zastava M70A is a reliable, historic pistol.",
            "fixed sights, 7 round mag, semi-automatic, compact design.",
            "offering a compact 6-round capacity in a purpose-built military pistol",
            "available in Standard, Tactical, and Compact variants.",
        ],
    )
    def test_a_descriptions_adjective_is_not_a_size(self, description):
        assert size("Some Pistol 9mm", description) is None

    def test_a_grip_is_not_the_gun(self):
        """A P320 Carry is a compact slide on a "Full-Size Grip"."""
        title = 'Sig Sauer P320 Carry .40 S&W 3.9" Barrel 14rd, Full-Size Grip'
        assert size(title) is None

    def test_a_named_version_in_a_description_counts(self):
        assert size("Tanfoglio Mossad 9mm", "Tanfoglio Mossad Compact 9mm Pistol") == "Compact"
        assert size("Pistol", "Model: P320 Frame Size: Compact Caliber: 9mm") == "Compact"

    @pytest.mark.parametrize(
        "title",
        [
            "U.S. Government Property marked M1911A1",
            "Colt Officer's Model Match .38 Special revolver",
            "Retired police officer's carry pistol",
        ],
    )
    def test_the_1911_names_only_as_the_1911s(self, title):
        assert size(title) is None


class TestARevolversFrame:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Smith & Wesson Model 64 K-Frame Stainless Steel 6-Shot Revolvers", "K-frame"),
            ("S&W 619 .357 MAGNUM REVOLVER 4″ BARREL, L FRAME, 4″ BARREL", "L-frame"),
            ("S&W Model 500 X-Frame 500 S&W Mag Revolver", "X-frame"),
            ("MERWIN & HULBERT DA MEDIUM FRAME REVOLVER", "Medium frame"),
        ],
    )
    def test_a_frame_letter_or_word(self, text, expected):
        assert size(text, revolver=True) == expected

    def test_a_revolver_is_not_read_for_a_pistols_size(self):
        assert size("S&W Model 640 Compact Revolver", revolver=True) is None


class TestTheVocabulary:
    def test_typed_values_are_read_into_it_or_refused(self):
        assert frames.checked("full-size") == "Full size"
        assert frames.checked("k-frame") == "K-frame"
        assert frames.checked("") is None
        with pytest.raises(frames.UnknownFrameSize):
            frames.checked("enormous")

    def test_a_variants_label(self):
        assert size('Walther PDP Pro SD Full Size 5.1" 9MM (2842521)', revolver=None) == "Full size"
        assert size("M&P9 M2.0 4 INCH METAL COMPACT THUMB SAFETY", revolver=None) == "Compact"
        assert size("Kimber Micro 9 Bel Air 9 mm (3700647)", revolver=None) == "Micro"


@pytest.fixture
def pdp(clean_db):
    model = FirearmModel(name="Walther PDP", status=ArmoryStatus.APPROVED, modern_production=True)
    clean_db.add(model)
    clean_db.flush()
    for label, frame in (
        ('PDP Full Size 4.5"', "Full size"),
        ('PDP Full Size 5"', "Full size"),
        ('PDP Compact 4"', "Compact"),
    ):
        clean_db.add(
            ModelVariant(
                model_id=model.id, label=label, frame_size=frame, status=ArmoryStatus.APPROVED
            )
        )
    site = Site(slug="fr", name="Shop FR", base_url="https://fr.test/")
    clean_db.add(site)
    clean_db.commit()
    return clean_db, model, site


def listing(session, model, site, title, key="a", kind="pistol"):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://fr.test/{key}",
        title=title,
        is_pistol=True,
        kind=kind,
        firearm_model_id=model.id,
        is_active=True,
        is_sold=False,
    )
    session.add(item)
    session.flush()
    variants.settle(session, item)
    session.commit()
    return item


class TestNarrowing:
    def test_a_stated_size_narrows_the_versions(self, pdp):
        session, model, site = pdp
        item = listing(session, model, site, "WALTHER PDP FS PRE OWNED")
        assert item.frame_size == "Full size"
        assert item.frame_quote == "WALTHER PDP FS PRE OWNED"
        assert sorted(v.label for v in variants.candidates(session, item)) == [
            'PDP Full Size 4.5"',
            'PDP Full Size 5"',
        ]

    def test_a_size_no_version_has_narrows_nothing(self, pdp):
        """Asked for: only "where both ... have a populated value and there is
        a matching variant"."""
        session, model, site = pdp
        item = listing(session, model, site, "WALTHER PDP SUBCOMPACT PRE OWNED")
        assert item.frame_size == "Subcompact"
        assert len(variants.candidates(session, item)) == 3

    def test_a_model_of_one_size_gives_it_to_a_silent_listing(self, pdp):
        session, model, site = pdp
        model.frame_size = "Compact"
        session.commit()
        item = listing(session, model, site, "WALTHER PDP PRE OWNED")
        assert (item.frame_size, item.frame_quote) == ("Compact", None)
        assert [v.label for v in variants.candidates(session, item)] == ['PDP Compact 4"']

    def test_not_a_handgun_has_none(self, pdp):
        session, model, site = pdp
        item = listing(session, model, site, "Full size flintlock pistol", kind="flintlock_pistol")
        assert item.frame_size is None


class TestTheArmory:
    def test_a_models_size_is_checked_and_its_listings_follow(self, pdp, client, admin_headers):
        session, model, site = pdp
        item = listing(session, model, site, "WALTHER PDP PRE OWNED")
        assert item.frame_size is None
        refused = client.patch(
            f"/api/armory/models/{model.id}", json={"frame_size": "huge"}, headers=admin_headers
        )
        assert refused.status_code == 422
        taken = client.patch(
            f"/api/armory/models/{model.id}",
            json={"frame_size": "compact"},
            headers=admin_headers,
        )
        assert taken.status_code == 200, taken.text
        assert taken.json()["model"]["frame_size"] == "Compact"
        session.expire_all()
        assert session.get(Item, item.id).frame_size == "Compact"

    def test_a_variants_size_is_typed_in_its_dialog(self, pdp, client, admin_headers):
        _session, model, _site = pdp
        made = client.post(
            f"/api/armory/models/{model.id}/variants",
            json={"label": "PDP F-Series", "frame_size": "full size"},
            headers=admin_headers,
        )
        assert made.status_code == 201, made.text
        assert made.json()["frame_size"] == "Full size"

    def test_both_travel_in_the_shipped_file(self, pdp, tmp_path):
        session, model, _site = pdp
        model.frame_size = "Compact"
        session.commit()
        path = tmp_path / "armory.yaml"
        armory.write_export(session, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        entry = next(m for m in written["models"] if m["name"] == "Walther PDP")
        assert entry["frame_size"] == "Compact"
        assert {v["frame"] for v in entry["variants"]} == {"Full size", "Compact"}
        assert not armory.plan_sync(session, path)

    def test_the_migration_reads_variant_labels(self, pdp):
        session, model, _site = pdp
        session.add(ModelVariant(model_id=model.id, label="PDP Subcompact 3.5", frame_size=None))
        session.commit()
        assert frames.label_variants(session) == 1
