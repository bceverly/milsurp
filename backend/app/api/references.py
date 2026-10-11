"""Wikipedia articles proposed for armory rows, accepted or rejected here.

The proposals are written by ``cli.py armory wikipedia``; see
``app.services.wikipedia``. Administrators only, like the rest of the armory.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import AdminUser, DbSession
from ..schemas import ArmoryIds, ReferenceDecision, ReferenceProposalOut
from ..services import armory as armory_service
from ..services import wikipedia

router = APIRouter(prefix="/armory/references", tags=["armory"])


@router.get("", response_model=list[ReferenceProposalOut])
def list_proposals(_admin: AdminUser, session: DbSession) -> list[ReferenceProposalOut]:
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
        )
        for proposal, name in wikipedia.pending(session)
    ]


@router.post("/accept", response_model=ReferenceDecision)
def accept(payload: ArmoryIds, admin: AdminUser, session: DbSession) -> ReferenceDecision:
    taken = wikipedia.accept(session, payload.ids, admin)
    armory_service.invalidate()
    return ReferenceDecision(changed=taken, message=f"{taken} link(s) added.")


@router.post("/accept-confident", response_model=ReferenceDecision)
def accept_confident(admin: AdminUser, session: DbSession) -> ReferenceDecision:
    ids = [proposal.id for proposal, _name in wikipedia.pending(session) if proposal.confident]
    taken = wikipedia.accept(session, ids, admin)
    armory_service.invalidate()
    return ReferenceDecision(changed=taken, message=f"{taken} link(s) added.")


@router.post("/reject", response_model=ReferenceDecision)
def reject(payload: ArmoryIds, _admin: AdminUser, session: DbSession) -> ReferenceDecision:
    count = wikipedia.reject(session, payload.ids)
    return ReferenceDecision(changed=count, message=f"{count} proposal(s) rejected.")
