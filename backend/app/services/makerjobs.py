"""The long jobs started from a button on Site settings.

Two reads of the manufacturers' own sites, each a command until 2026-10-13
and now a button too, and since 2026-10-14 a re-read of the catalog itself:

* **variants** -- app.services.makersites: each modern model's versions, with
  MSRP, barrel, finish and UPC, from the readers built for Ruger, Smith &
  Wesson, Kimber and Walther. They arrive as pending variants, approved in
  each model's dialog on the Armory.
* **pages** -- app.services.makerpages: each modern model's own page on its
  manufacturer's site, suggested on the Armory's Manufacturer pages tab.
* **barrels** -- app.services.barrels and app.services.frames: every stored
  gun's barrel length and threading, and every handgun's frame size, read
  again from its own words, as ``cli.py barrels-backfill`` does,
  and the listings of models still made matched to their versions again. No
  site is asked anything.

Neither runs on a clock. The button sets ``requested_at``; the scheduler
looks once a minute, runs one at a time on the reference worker, and records
how it went on the row the page shows.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ManufacturerJob, utcnow
from ..scrapers.base import ScrapeContext

#: The jobs, in the order the page shows them.
JOBS = ("variants", "pages", "barrels")


def job(session: Session, name: str) -> ManufacturerJob:
    if name not in JOBS:
        raise ValueError(f"No such job: {name!r}. The jobs are {', '.join(JOBS)}.")
    row = session.get(ManufacturerJob, name)
    if row is None:
        row = ManufacturerJob(name=name)
        session.add(row)
        session.commit()
    return row


def all_jobs(session: Session) -> list[ManufacturerJob]:
    return [job(session, name) for name in JOBS]


def ask(session: Session, name: str) -> ManufacturerJob:
    """Ask the scheduler to run *name* on its next minute."""
    row = job(session, name)
    row.requested_at = utcnow()
    session.commit()
    return row


def requested(session: Session) -> list[str]:
    """The jobs somebody has asked for, oldest request first."""
    return list(
        session.execute(
            select(ManufacturerJob.name)
            .where(ManufacturerJob.requested_at.is_not(None))
            .order_by(ManufacturerJob.requested_at)
        ).scalars()
    )


def _summary(name: str, counts: dict[str, Any]) -> str:
    if name == "barrels":
        return (
            f"Read {counts.get('examined', 0):,} gun(s): {counts.get('length', 0):,} barrel "
            f"length(s), {counts.get('threaded', 0):,} threaded, "
            f"{counts.get('not_threaded', 0):,} stated not threaded; "
            f"{counts.get('frames_stated', 0):,} frame size(s) stated and "
            f"{counts.get('frames_from_armory', 0):,} from the armory; "
            f"{counts.get('relinked', 0):,} listing(s) matched to a different version."
        )
    if name == "variants":
        return (
            f"Read {counts.get('models', 0)} model(s): {counts.get('proposed', 0)} variant(s) "
            f"proposed, {counts.get('refreshed', 0)} brought up to date, "
            f"{counts.get('unread', 0)} with no page found."
        )
    return (
        f"Asked about {counts.get('asked', 0)} model(s): {counts.get('proposed', 0)} page(s) "
        f"suggested, {counts.get('confident', 0)} of them confident; "
        f"{counts.get('nothing', 0)} with no page found."
    )


def run(session: Session, ctx: ScrapeContext, name: str, log: Callable[[str], None] = print) -> str:
    """Run one job now, recording how it went. Returns its summary."""
    from . import barrels, makerpages, makersites

    started = time.monotonic()
    row = job(session, name)
    row.requested_at = None
    session.commit()
    try:
        if name == "barrels":
            counts = barrels.refresh(session)
        elif name == "variants":
            counts = makersites.run(session, ctx, log=log)
        else:
            counts = makerpages.run(session, ctx, log=log)
        summary, status = _summary(name, counts), "ok"
    except Exception as exc:  # recorded where Site settings shows it
        session.rollback()
        summary, status = f"Failed: {exc}", "failed"
    row = job(session, name)
    row.last_run_at = utcnow()
    row.last_status = status
    row.last_summary = summary[:500]
    row.last_seconds = round(time.monotonic() - started, 1)
    session.commit()
    return summary
