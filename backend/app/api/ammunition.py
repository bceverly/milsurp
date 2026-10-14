"""What it costs to shoot a caliber, and how often that is refreshed.

The Ammunition information panel reads ``GET /api/ammunition?caliber=``, for
any signed-in reader; the refresh frequency and the refresh buttons -- one
per part, and one for all three -- are an administrator's, on the Caliber
data page. See ``app.services.ammunition``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ..deps import AdminUser, CurrentUser, DbSession
from ..schemas import (
    AmmoRefreshIn,
    AmmoSettingsOut,
    AmmoSettingsUpdate,
    AmmunitionOut,
    BulletWeightOut,
    PowderOut,
)
from ..services import ammunition, reloading

router = APIRouter(prefix="/ammunition", tags=["ammunition"])


def _settings_out(session: DbSession) -> AmmoSettingsOut:
    out = AmmoSettingsOut.model_validate(ammunition.settings(session), from_attributes=True)
    out.choices = dict(ammunition.FREQUENCIES)
    return out


@router.get("", response_model=AmmunitionOut)
def for_caliber(
    _user: CurrentUser, session: DbSession, caliber: str = Query(min_length=1, max_length=128)
) -> AmmunitionOut:
    row = ammunition.facts(session, caliber)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No caliber called {caliber!r}.")
    powder = reloading.supply(session, reloading.POWDER, row.powder_name)
    return AmmunitionOut(
        caliber_id=row.id,
        caliber=row.name,
        wikipedia_url=row.wikipedia_url,
        bullet_diameter_in=row.bullet_diameter_in,
        bullet_weights=[BulletWeightOut.model_validate(w) for w in row.bullet_weights],
        factory_cpr=row.factory_cpr,
        factory_source=row.factory_source,
        factory_url=row.factory_url,
        factory_checked_at=row.factory_checked_at,
        lee_dies=row.lee_dies,
        lee_url=row.lee_url,
        lee_checked_at=row.lee_checked_at,
        projectile_cost=row.projectile_cost,
        projectile_url=row.projectile_url,
        projectile_checked_at=row.projectile_checked_at,
        primer_size=row.primer_size,
        primer_magnum=row.primer_magnum,
        primer_source=row.primer_source,
        powder_name=row.powder_name,
        powder_charge_gr=row.powder_charge_gr,
        powder_bullet_gr=row.powder_bullet_gr,
        brass_cost=row.brass_cost,
        brass_url=row.brass_url,
        brass_checked_at=row.brass_checked_at,
        primer_cost=row.primer_cost,
        primer_url=row.primer_url,
        powder_cost=row.powder_cost,
        powder_url=row.powder_url,
        powder_per_pound=powder.unit_price if powder else None,
        powder_in_stock=powder.in_stock if powder else None,
        bullet_cost=reloading.bullet_cost(row),
        reload_cost=reloading.reload_cost(row),
    )


@router.get("/powders", response_model=list[PowderOut])
def powders(_user: CurrentUser, session: DbSession) -> list[PowderOut]:
    """Every powder Graf & Sons sells or has sold, for a load's dropdown."""
    return [PowderOut.model_validate(row) for row in reloading.powders(session)]


@router.get("/settings", response_model=AmmoSettingsOut)
def get_settings(_admin: AdminUser, session: DbSession) -> AmmoSettingsOut:
    return _settings_out(session)


@router.patch("/settings", response_model=AmmoSettingsOut)
def update_settings(
    payload: AmmoSettingsUpdate, _admin: AdminUser, session: DbSession
) -> AmmoSettingsOut:
    if payload.refresh_days not in ammunition.FREQUENCIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The caliber data refreshes daily, weekly or every 2 weeks.",
        )
    ammunition.settings(session).refresh_days = payload.refresh_days
    session.commit()
    return _settings_out(session)


@router.post("/refresh", response_model=AmmoSettingsOut)
def refresh_now(
    _admin: AdminUser, session: DbSession, payload: AmmoRefreshIn | None = None
) -> AmmoSettingsOut:
    """Ask for a refresh of some parts, or all of them with no body; the
    scheduler starts it on its next tick."""
    parts = payload.parts if payload and payload.parts else list(ammunition.PARTS)
    unknown = sorted(set(parts) - set(ammunition.PARTS))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"No such part of the caliber data: {', '.join(unknown)}.",
        )
    ammunition.ask_for(session, parts)
    return _settings_out(session)
