"""Wikipedia articles proposed for armory rows, accepted or rejected here.

The proposals are written by ``cli.py armory wikipedia`` (see
``app.services.wikipedia``) and, for a model's page on its maker's site, by
``cli.py armory maker-pages`` (``app.services.makerpages``). Administrators only, like the rest of the armory.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..deps import AdminUser, DbSession
from ..schemas import ArmoryIds, ReferenceDecision, ReferenceProposalOut
from ..services import armory as armory_service
from ..services import wikipedia

router = APIRouter(prefix="/armory/references", tags=["armory"])


#: Which kind of suggestion: a Wikipedia article or a model's page on its
#: maker's site (app.services.makerpages). Every kind, left out.
FIELD = Query(default=None, pattern="^(wikipedia|maker_page)$")


@router.get("", response_model=list[ReferenceProposalOut])
def list_proposals(
    _admin: AdminUser, session: DbSession, field: str | None = FIELD
) -> list[ReferenceProposalOut]:
    return [
        ReferenceProposalOut(
            id=proposal.id,
            target_type=proposal.target_type,
            target_id=proposal.target_id,
            target_name=name,
            url=proposal.url,
            title=proposal.title,
            confident=proposal.confident,
            reason=proposal.reason,
            field=proposal.field,
        )
        for proposal, name in wikipedia.pending(session, field)
    ]


@router.post("/accept", response_model=ReferenceDecision)
def accept(payload: ArmoryIds, admin: AdminUser, session: DbSession) -> ReferenceDecision:
    taken = wikipedia.accept(session, payload.ids, admin)
    armory_service.invalidate()
    return ReferenceDecision(changed=taken, message=f"{taken} link(s) added.")


@router.post("/accept-confident", response_model=ReferenceDecision)
def accept_confident(
    admin: AdminUser, session: DbSession, field: str | None = FIELD
) -> ReferenceDecision:
    ids = [
        proposal.id for proposal, _name in wikipedia.pending(session, field) if proposal.confident
    ]
    taken = wikipedia.accept(session, ids, admin)
    armory_service.invalidate()
    return ReferenceDecision(changed=taken, message=f"{taken} link(s) added.")


@router.post("/reject", response_model=ReferenceDecision)
def reject(payload: ArmoryIds, _admin: AdminUser, session: DbSession) -> ReferenceDecision:
    count = wikipedia.reject(session, payload.ids)
    return ReferenceDecision(changed=count, message=f"{count} proposal(s) rejected.")
