"""What a kind of gun goes for, across every dealer at once.

The detail page answers "is this a good deal?" for one listing by placing it
among others of the same model. This is the same question one level up, which
is the one somebody has before they have a listing in front of them.

Signed-in rather than admin-only: it is a reader's page, not an operator's.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..deps import CurrentUser, DbSession
from ..schemas import MarketBandOut, MarketOut, TurnoverOut, TurnoverRowOut
from ..services import market

router = APIRouter(prefix="/market", tags=["market"])


@router.get("", response_model=MarketOut)
def price_bands(
    _user: CurrentUser,
    session: DbSession,
    by: str = Query(default="caliber"),
    include_accessories: bool = Query(default=False),
    min_sample: int = Query(default=market.MIN_SAMPLE, ge=2, le=100),
) -> MarketOut:
    """Price bands for one dimension, commonest first.

    The accessory switch is spelled as the *non-default* -- include rather than
    exclude -- because the client's query builder drops a false boolean
    entirely, which is the right convention for a flag whose absence means off
    and precisely wrong for one whose server default is on. Written the other
    way round, unchecking the box sent nothing, the default applied, and the
    switch silently did nothing at all.
    """
    if by not in market.DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown dimension. Valid: {', '.join(market.DIMENSIONS)}.",
        )
    result = market.summarize(
        session, by, firearms_only=not include_accessories, min_sample=min_sample
    )
    return MarketOut(
        dimension=result.dimension,
        firearms_only=result.firearms_only,
        min_sample=result.min_sample,
        considered=result.considered,
        thin_groups=result.thin_groups,
        thin_listings=result.thin_listings,
        bands=[
            MarketBandOut(
                value=band.value,
                listings=band.listings,
                low=band.low,
                median=band.median,
                high=band.high,
                currency=band.currency,
                sites=band.sites,
                top_site_share=band.top_site_share,
                concentrated=band.concentrated,
            )
            for band in result.bands
        ],
    )


@router.get("/time-to-sell", response_model=TurnoverOut)
def time_to_sell(
    _user: CurrentUser,
    session: DbSession,
    by: str = Query(default="model"),
    min_sample: int = Query(default=market.MIN_SAMPLE, ge=2, le=100),
) -> TurnoverOut:
    """How long each kind of gun stays on the shelf, fastest first."""
    if by not in market.TURNOVER_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown dimension. Valid: {', '.join(market.TURNOVER_DIMENSIONS)}.",
        )
    result = market.time_to_sell(session, by, min_sample=min_sample)
    return TurnoverOut(
        dimension=result.dimension,
        min_sample=result.min_sample,
        measured=result.measured,
        floors=result.floors,
        thin_groups=result.thin_groups,
        thin_listings=result.thin_listings,
        rows=[
            TurnoverRowOut(
                value=row.value,
                sold=row.sold,
                median_days=row.median_days,
                fast_days=row.fast_days,
                slow_days=row.slow_days,
                sites=row.sites,
                top_site_share=row.top_site_share,
                concentrated=row.concentrated,
            )
            for row in result.rows
        ],
    )
