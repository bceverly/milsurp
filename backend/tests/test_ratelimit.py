"""The attempt register, and the leak it exists to prevent.

The bug these cover is not that throttling was wrong -- it counted correctly
throughout -- but that the structure doing the counting grew forever, keyed in
part by a string the attacker chooses. See ``app/ratelimit.py``.
"""

from __future__ import annotations

import time

import pytest

from app.ratelimit import AttemptRegister


@pytest.fixture
def register():
    return AttemptRegister(window_seconds=300)


class TestCounting:
    def test_an_unseen_key_has_no_attempts(self, register):
        assert register.recent("nobody") == []

    def test_attempts_accumulate(self, register):
        for _ in range(3):
            register.record("a")
        assert len(register.recent("a")) == 3

    def test_keys_do_not_see_each_other(self, register):
        register.record("a")
        assert register.recent("b") == []

    def test_clearing_forgets_a_key(self, register):
        register.record("a")
        register.clear("a")
        assert register.recent("a") == []

    def test_the_oldest_time_comes_first(self, register):
        """The caller works out how long is left from it, so the order is part
        of the contract rather than an accident of the list."""
        register.record("a")
        time.sleep(0.01)
        register.record("a")
        times = register.recent("a")
        assert times == sorted(times)

    def test_the_returned_list_is_a_copy(self, register):
        """A caller holding the register's own list could mutate a count."""
        register.record("a")
        register.recent("a").append(0.0)
        assert len(register.recent("a")) == 1


class TestExpiry:
    def test_attempts_outside_the_window_stop_counting(self):
        register = AttemptRegister(window_seconds=0.05)
        register.record("a")
        time.sleep(0.06)
        assert register.recent("a") == []

    def test_and_the_key_itself_is_dropped(self):
        """The leak, stated directly. Counting correctly while keeping the key
        forever is what the old code did."""
        register = AttemptRegister(window_seconds=0.05)
        register.record("a")
        time.sleep(0.06)
        register.recent("a")
        assert len(register) == 0

    def test_reading_an_unknown_key_does_not_create_one(self, register):
        register.recent("never-seen")
        assert len(register) == 0


class TestTheCeiling:
    def test_stale_keys_are_swept_when_it_grows(self):
        register = AttemptRegister(window_seconds=0.05, max_keys=10)
        for i in range(10):
            register.record(f"stale{i}")
        time.sleep(0.06)
        for i in range(5):
            register.record(f"live{i}")
        # The stale ten are gone without anybody asking about them by name.
        assert len(register) == 5

    def test_it_never_exceeds_the_ceiling_even_when_every_key_is_live(self):
        """The distributed case: nothing is stale, so something must go."""
        register = AttemptRegister(window_seconds=300, max_keys=20)
        for i in range(500):
            register.record(f"attacker{i}")
        assert len(register) <= 20

    def test_the_most_recent_keys_are_the_ones_kept(self):
        register = AttemptRegister(window_seconds=300, max_keys=10)
        for i in range(40):
            register.record(f"k{i}")
            time.sleep(0.001)
        survivors = {k for k in (f"k{i}" for i in range(40)) if register.recent(k)}
        assert "k39" in survivors
        assert "k0" not in survivors

    def test_running_out_of_room_is_logged(self):
        """Being at the ceiling is the only signal that throttling is being
        outrun, so the line has to actually come out.

        Captured with a handler attached straight to the logger rather than
        with caplog: the suite configures logging elsewhere, and this assertion
        should be about the register, not about test ordering.
        """
        import logging as _logging

        records = []

        class Catcher(_logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = _logging.getLogger("milsurp.ratelimit")
        handler = Catcher()
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(_logging.WARNING)
        try:
            register = AttemptRegister(window_seconds=300, max_keys=5)
            for i in range(50):
                register.record(f"k{i}")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

        assert any("register is full" in message for message in records)

    def test_a_flood_of_distinct_keys_does_not_grow_without_bound(self):
        """The whole point, at the scale that made it a real problem: an
        attacker varying the username never trips a per-key throttle, so the
        only thing standing between them and the machine's memory is this."""
        register = AttemptRegister(window_seconds=3600, max_keys=1_000)
        for i in range(50_000):
            register.record(f"victim{i}|203.0.113.7")
        assert len(register) <= 1_000


class TestConcurrency:
    def test_parallel_writers_do_not_lose_or_corrupt_counts(self):
        import threading

        register = AttemptRegister(window_seconds=300)
        barrier = threading.Barrier(8)

        def hammer():
            barrier.wait()
            for _ in range(200):
                register.record("shared")

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(register.recent("shared")) == 8 * 200


class TestTheCeilingIsCheap:
    def test_a_full_register_does_not_pay_a_sort_per_insert(self):
        """The first version of the ceiling evicted exactly one key per insert,
        so the sort ran on every request once full: an O(n log n) cost paid
        under exactly the flood it was defending against. Evicting down to a
        low-water mark amortizes it. The gap between the two is large -- 18x on
        the suite -- so a loose bound here still catches a regression."""
        import time as _time

        register = AttemptRegister(window_seconds=3600, max_keys=2_000)
        for i in range(2_000):  # fill it
            register.record(f"fill{i}")

        started = _time.monotonic()
        for i in range(20_000):  # now run it at the ceiling
            register.record(f"flood{i}")
        per_insert_us = (_time.monotonic() - started) / 20_000 * 1e6

        assert len(register) <= 2_000
        assert per_insert_us < 50, f"{per_insert_us:.1f}us per insert at the ceiling"
