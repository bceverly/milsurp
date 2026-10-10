"""A reader's FFL dealers: who will receive a gun for them, and for how much.

Scoped to ``CurrentUser.id`` like the wishlist. Every delivered price uses the
lowest fee among them -- see ``User.ffl_transfer_fee``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession
from ..models import FflDealer, User
from ..schemas import FflDealerIn, FflDealerOut

router = APIRouter(prefix="/dealers", tags=["dealers"])


def _list(user: User) -> list[FflDealerOut]:
    cheapest = user.cheapest_dealer
    return [
        FflDealerOut.model_validate(dealer).model_copy(update={"lowest": dealer is cheapest})
        for dealer in user.ffl_dealers
    ]


def _own(session: DbSession, user: User, dealer_id: int) -> FflDealer:
    dealer = session.get(FflDealer, dealer_id)
    if dealer is None or dealer.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such dealer.")
    return dealer


@router.get("", response_model=list[FflDealerOut])
def list_dealers(user: CurrentUser) -> list[FflDealerOut]:
    return _list(user)


@router.post("", response_model=list[FflDealerOut], status_code=status.HTTP_201_CREATED)
def add_dealer(payload: FflDealerIn, user: CurrentUser, session: DbSession) -> list[FflDealerOut]:
    """Add one, and answer with the whole list: which is cheapest may change."""
    user.ffl_dealers.append(FflDealer(**payload.model_dump()))
    session.commit()
    return _list(user)


@router.put("/{dealer_id}", response_model=list[FflDealerOut])
def update_dealer(
    dealer_id: int, payload: FflDealerIn, user: CurrentUser, session: DbSession
) -> list[FflDealerOut]:
    dealer = _own(session, user, dealer_id)
    for key, value in payload.model_dump().items():
        setattr(dealer, key, value)
    session.commit()
    session.refresh(user)
    return _list(user)


@router.delete("/{dealer_id}", response_model=list[FflDealerOut])
def delete_dealer(dealer_id: int, user: CurrentUser, session: DbSession) -> list[FflDealerOut]:
    dealer = _own(session, user, dealer_id)
    session.delete(dealer)
    session.commit()
    session.refresh(user)
    return _list(user)
