"""The reads of the manufacturers' own sites, from Site settings.

``GET /api/manufacturer-data`` says how each last went; ``POST
/api/manufacturer-data/{name}/run`` asks the scheduler for one. Administrators
only. See app.services.makerjobs.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import AdminUser, DbSession
from ..schemas import ManufacturerJobOut
from ..services import makerjobs

router = APIRouter(prefix="/manufacturer-data", tags=["armory"])


def _all(session: DbSession) -> list[ManufacturerJobOut]:
    return [ManufacturerJobOut.model_validate(row) for row in makerjobs.all_jobs(session)]


@router.get("", response_model=list[ManufacturerJobOut])
def list_jobs(_admin: AdminUser, session: DbSession) -> list[ManufacturerJobOut]:
    return _all(session)


@router.post("/{name}/run", response_model=list[ManufacturerJobOut])
def run_job(name: str, _admin: AdminUser, session: DbSession) -> list[ManufacturerJobOut]:
    if name not in makerjobs.JOBS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such job: {name!r}.")
    makerjobs.ask(session, name)
    return _all(session)
