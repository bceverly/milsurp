"""A register of recent attempt times per key, with a ceiling on its size.

Two endpoints throttle in memory rather than in Redis, because this is a
single-worker application and a shared dict is the whole mechanism: failed
sign-ins, counted per (username, address), and access-request submissions,
counted per address. Both were written as a plain ``dict[str, list[float]]``
and both leaked.

**The leak, and why it is worth a module.** Pruning happened only on the key
being looked at, and wrote the pruned list back even when it was empty::

    recent = [t for t in _attempts.get(key, []) if now - t < WINDOW]
    _attempts[key] = recent          # an empty list, kept forever

So a key was created on first sight and never removed unless that exact key was
seen again *and* its owner signed in successfully. The sign-in key includes the
submitted username, which the attacker chooses, so every guess against a
different name stranded another entry: 171 bytes each, measured, permanently.
At nginx's per-address ceiling of ten sign-ins a minute that is 2 MiB a day
from one address, and a thousand addresses -- an unremarkable botnet -- is
2.3 GiB a day, with no valid credentials needed and nothing in the logs but
failed sign-ins. A throttle that exhausts the machine it protects is not a
throttle.

So this holds the invariant the call sites kept getting wrong: **the register
never holds more than ``max_keys`` entries.** Stale keys are swept when it
grows, and if a sweep cannot get it under the ceiling -- which means that many
*live* attackers at once -- the least recently touched are evicted and the
eviction is logged, because being at the ceiling is itself worth knowing about.

Eviction weakens throttling for the evicted key, and that is the right way
round. The alternative is unbounded growth, which takes the site down for
everybody rather than letting one attacker's counter reset early, and reaching
the ceiling at all needs a distributed flood that nginx is already limiting.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("milsurp.ratelimit")

#: Keys held before a sweep is forced. 50,000 is about 8.5 MiB at the measured
#: 171 bytes an entry -- large enough that ordinary use never approaches it,
#: small enough to be an unremarkable amount of memory to have set aside.
DEFAULT_MAX_KEYS = 50_000

#: How far an eviction cuts back, as a fraction of the ceiling. The gap is what
#: keeps the sort off the hot path; see _enforce_ceiling.
EVICT_TO = 0.9


class AttemptRegister:
    """Timestamps of recent attempts, per key, bounded in size.

    Not a general rate limiter: it counts and reports, and the caller decides
    what a count means. The two call sites answer differently -- one locks out
    for five minutes, the other refuses for an hour -- and neither wants a
    policy baked in here.
    """

    def __init__(self, window_seconds: float, max_keys: int = DEFAULT_MAX_KEYS) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._times: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # -- reading ------------------------------------------------------------
    def recent(self, key: str) -> list[float]:
        """Attempt times still inside the window, oldest first.

        A copy: the caller reads the oldest entry to work out how long is left,
        and must not be holding a list this register may later mutate.
        """
        with self._lock:
            return list(self._prune(key, time.monotonic()))

    # -- writing ------------------------------------------------------------
    def record(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            # _prune returns the in-dict list when there is one and a fresh
            # list when there is not (it deletes the key as it empties it), so
            # the append has to be followed by an insert to cover both.
            times = self._prune(key, now)
            times.append(now)
            self._times[key] = times
            if len(self._times) > self.max_keys:
                self._enforce_ceiling(now)

    def clear(self, key: str) -> None:
        """Forget a key entirely -- a successful sign-in, typically."""
        with self._lock:
            self._times.pop(key, None)

    def reset(self) -> None:
        """Forget everything. For tests; nothing in the application wants it.

        Deliberately not ``clear()`` with the key left off. That reads like the
        dict method it replaced, and a throttle that silently forgets every
        attempt because an argument was omitted is the wrong thing to make easy
        to write by accident.
        """
        with self._lock:
            self._times.clear()

    # -- internals ----------------------------------------------------------
    def _prune(self, key: str, now: float) -> list[float]:
        """Drop this key's expired times, and the key itself once it is empty.

        Removing the empty key is the fix for the leak; keeping it was the bug.
        Returns the live list, which is inserted only when it has something in
        it -- so a read of an unknown key does not create one.
        """
        times = self._times.get(key)
        if times is None:
            return []
        times[:] = [t for t in times if now - t < self.window_seconds]
        if not times:
            del self._times[key]
        return times

    def _enforce_ceiling(self, now: float) -> None:
        """Called with the lock held, and only when over ``max_keys``."""
        for key in [
            k for k, ts in self._times.items() if all(now - t >= self.window_seconds for t in ts)
        ]:
            del self._times[key]
        if len(self._times) <= self.max_keys:
            return

        # Everything left is live, which is the distributed case. Drop the
        # least recently touched and say so: the log line is the only evidence
        # that throttling is being outrun.
        #
        # Down to a low-water mark rather than exactly to the ceiling, and the
        # reason is not tidiness. Evicting one key per insert would run this
        # sort on *every* request once the register was full -- turning the fix
        # for a memory leak into an O(n log n) CPU cost paid under precisely
        # the flood it defends against, which is a worse bug than the one being
        # fixed. Leaving a tenth of the ceiling free means it runs once per
        # that many inserts instead.
        target = int(self.max_keys * EVICT_TO)
        over = len(self._times) - target
        oldest = sorted(self._times, key=lambda k: self._times[k][-1])[:over]
        for key in oldest:
            del self._times[key]
        log.warning(
            "Attempt register is full at %s keys; evicted %s of the least recent, "
            "leaving %s. This is what a distributed flood looks like.",
            self.max_keys,
            over,
            len(self._times),
        )

    # -- for tests ----------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._times)
