"""What the armory's Showing filter means, and why it is not the row's status.

The bug this was written for: **two manufacturers switched off by hand went on
appearing under "Awaiting approval" forever**, and kept the nav badge lit at 2.
Turning a row off *is* ruling on it -- it matches nothing afterwards, exactly
like a pending row -- but the filter asked only whether the status was PENDING,
so a decision that had already been made kept being asked about.

Approving them instead would have been worse: "Production" would then have
meant both "yes, use this" and "no, never", and fifty models were already
sitting in approved-and-disabled as the de-facto ruled-out state.

So "Disabled" is its own bucket. The trap, and the reason this file exists
rather than a one-line change, is that **merging a row away also switches it
off** -- so a naive "not enabled" bucket fills with every merge ever made.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import ArmoryStatus, Manufacturer
from app.services.armory import ArmoryView, filter_by_view, pending_counts


@pytest.fixture
def makers(seeded):
    """One row in each state the filter has to tell apart."""
    rows = {
        "waiting": Manufacturer(name="Waiting", status=ArmoryStatus.PENDING, enabled=True),
        "ruled_out": Manufacturer(name="RuledOut", status=ArmoryStatus.PENDING, enabled=False),
        "live": Manufacturer(name="Live", status=ArmoryStatus.APPROVED, enabled=True),
        "retired": Manufacturer(name="Retired", status=ArmoryStatus.APPROVED, enabled=False),
        "folded": Manufacturer(name="Folded", status=ArmoryStatus.MERGED, enabled=False),
    }
    seeded.add_all(rows.values())
    seeded.commit()
    return rows


def _names(session, view):
    stmt = filter_by_view(select(Manufacturer.name), Manufacturer, view)
    return set(session.execute(stmt).scalars())


class TestSwitchingARowOffIsRulingOnIt:
    def test_it_leaves_the_queue(self, seeded, makers):
        """The reported bug. "Awaiting approval" means nobody has looked at
        this yet, not "this is not approved"."""
        assert "RuledOut" not in _names(seeded, ArmoryView.PENDING)

    def test_and_the_badge_agrees(self, seeded, makers):
        """A badge counting rows the tab it links to does not show sends
        somebody hunting for two manufacturers that are not there."""
        assert pending_counts(seeded)["manufacturers"] == 1

    def test_what_is_left_is_genuinely_unanswered(self, seeded, makers):
        assert _names(seeded, ArmoryView.PENDING) == {"Waiting"}


class TestProductionIsWhatIsInUse:
    def test_a_switched_off_row_is_not_in_it(self, seeded, makers):
        """Fifty models were sitting here greyed out. Greyed out in a list
        called Production is not where a rejected row belongs."""
        assert _names(seeded, ArmoryView.APPROVED) == {"Live"}


class TestTheDisabledBucket:
    def test_it_gathers_them_from_both_sides(self, seeded, makers):
        """Which is the point of having it: the ruled-out rows were split
        across two tabs depending on what their status happened to be."""
        assert _names(seeded, ArmoryView.DISABLED) == {"RuledOut", "Retired"}

    def test_a_merged_row_is_not_in_it(self, seeded, makers):
        """merge_manufacturers switches the source off, so "not enabled"
        alone would fill this with every merge ever made -- which are not
        decisions about the row's own usefulness and have their own bucket."""
        assert "Folded" not in _names(seeded, ArmoryView.DISABLED)

    def test_and_is_still_where_merges_go(self, seeded, makers):
        assert _names(seeded, ArmoryView.MERGED) == {"Folded"}


class TestEverything:
    def test_no_filter_hides_nothing(self, seeded, makers):
        """Whatever the buckets do, there has to be one view that shows a row
        in any state at all."""
        total = seeded.scalar(select(func.count(Manufacturer.id)))
        assert len(_names(seeded, None)) == total


class TestOverTheRoute:
    """The same rules where the page actually asks for them."""

    @pytest.mark.parametrize(
        "path", ["/api/manufacturers", "/api/armory/calibers", "/api/armory/models"]
    )
    def test_disabled_is_a_filter_the_page_may_ask_for(self, client, admin_headers, path):
        response = client.get(f"{path}?status=disabled", headers=admin_headers)
        assert response.status_code == 200

    def test_and_a_switched_off_maker_is_returned_by_it(self, client, admin_headers, makers):
        response = client.get("/api/manufacturers?status=disabled", headers=admin_headers)
        assert {row["name"] for row in response.json()} == {"RuledOut", "Retired"}

    def test_but_not_by_the_queue(self, client, admin_headers, makers):
        response = client.get("/api/manufacturers?status=pending", headers=admin_headers)
        assert {row["name"] for row in response.json()} == {"Waiting"}

    def test_a_filter_that_is_not_one_is_refused(self, client, admin_headers):
        """Rather than quietly answering with everything, which would read as
        a filter that does not work."""
        response = client.get("/api/manufacturers?status=nonsense", headers=admin_headers)
        assert response.status_code == 422
