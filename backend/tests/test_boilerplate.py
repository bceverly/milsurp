"""Taking the shop's standing notices off the end of a description.

Every dealer ends listings the same way -- how to send an FFL, what they will
not ship to California, when they take a card. It is true, it is theirs, and it
is identical on every listing they publish, so it tells a reader nothing about
*this* rifle while pushing the part that does off the screen. 1,387 active
listings carry an FFL notice; 336 a returns policy.

**The tests that matter here are the ones about not cutting.** Leaving
boilerplate in is a small harm; eating a description is a large one, and both
of the guards below exist because an earlier version did exactly that on real
catalog data.
"""

from __future__ import annotations

from app.services.boilerplate import MIN_KEPT_CHARS, strip_boilerplate

REAL = (
    "A Yugoslavian M48 in very good condition. The bore is bright with strong "
    "rifling and the stock is sound."
)


class TestWhatItTakesOff:
    def test_a_trailing_ffl_notice(self):
        out = strip_boilerplate(REAL + " C&R or FFL required.")
        assert out == REAL

    def test_a_whole_trailing_block(self):
        out = strip_boilerplate(
            REAL + " Please upload your license at checkout. We ship within two days."
        )
        assert out == REAL

    def test_a_disclaimer_heading_mid_sentence(self):
        """Dealers write condition notes with no full stops, so the notes and
        the disclaimer arrive as one sentence. Cutting at the marker keeps the
        half a buyer reads."""
        text = (
            "A Russian M91/30 dated 1943, Izhevsk arsenal, with a matching bolt and "
            "floorplate. The stock has the usual handling marks for a wartime rifle. "
            "Light pitting on receiver Light grease on barrel No external pitting on "
            "barrel Visible and clean rifling "
            "DISCLAIMER: Firearms are subject to state-specific shipping restrictions "
            "and must be transferred through a valid FFL dealer."
        )
        out = strip_boilerplate(text)
        assert "clean rifling" in out
        assert "DISCLAIMER" not in out

    def test_but_not_when_the_disclaimer_is_most_of_the_text(self):
        """The share guard outranks the heading. A short listing that is mostly
        policy has little description to protect, and cutting it to a fragment
        is the larger harm -- so nothing is cut and the notice stays."""
        text = (
            "Light pitting on receiver Visible and clean rifling "
            "DISCLAIMER: Firearms are subject to state-specific shipping restrictions "
            "and must be transferred through a valid FFL dealer."
        )
        assert strip_boilerplate(text) == text


class TestWhatItRefusesToTouch:
    def test_a_description_that_is_only_a_compliance_note(self):
        """26 characters, every one of them useful: C&R eligibility is a fact
        about the gun. Trimming this to nothing makes the listing worse."""
        assert strip_boilerplate("Description **C&R FFL OK**") == "Description **C&R FFL OK**"

    def test_a_parts_kit_contents_list(self):
        """No full stops anywhere, so the splitter sees one long sentence. An
        earlier version matched something incidental inside it and removed a
        real 700-character description. Four listings lost 59% that way."""
        text = (
            "Ideal for a new build, our HK21 Parts Kit in 7.62x51mm offers authentic "
            "German engineering. This kit includes: HK21 Parts Kit Bolt group, complete "
            "Buttstock, complete with recoil spring and guide rod Backplate, complete "
            "Barrel grip with protective liner and grip Bipod, complete Carry handle"
        )
        out = strip_boilerplate(text)
        assert "Bolt group" in out

    def test_a_policy_sentence_in_the_middle_is_left_alone(self):
        """Working backwards and stopping at the first sentence that is not
        boilerplate means the middle is never reached. "Shipped to my FFL in
        1962" is part of a story somebody is telling about a gun."""
        text = "It was shipped to my FFL in 1962. " + REAL
        assert strip_boilerplate(text) == text

    def test_nothing_is_returned_as_nothing(self):
        for value in (None, "", "   "):
            assert strip_boilerplate(value) == value

    def test_the_floor_is_respected(self):
        short = "Nice rifle. FFL required."
        assert len(short) < MIN_KEPT_CHARS * 2
        # Trimming would leave "Nice rifle." which is under the floor.
        assert strip_boilerplate(short) == short

    def test_a_description_with_no_boilerplate_is_returned_unchanged(self):
        assert strip_boilerplate(REAL) == REAL
