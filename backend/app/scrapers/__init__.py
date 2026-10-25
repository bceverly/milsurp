"""Scraper registry.

Adding a vendor is a two-line change: write the scraper class in this package,
then list it in :data:`SCRAPER_CLASSES`. Startup reconciles the registry against
the ``sites`` table -- new scrapers get a row, and a row whose scraper has been
removed is flagged unavailable rather than deleted, so its history survives.
"""

from __future__ import annotations

import os

from .aim_surplus import AimSurplusScraper
from .allegheny_arsenal import AlleghenyArsenalScraper
from .ancestry_guns import AncestryGunsScraper
from .antique_weapon_store import AntiqueWeaponStoreScraper
from .apex_gun_parts import ApexGunPartsScraper
from .arms_of_america import ArmsOfAmericaScraper
from .arms_unlimited import ArmsUnlimitedScraper
from .atlantic_firearms import AtlanticFirearmsScraper
from .axis_arms import AxisArmsScraper
from .b4_antiques import B4AntiquesScraper
from .base import (
    Disallowed,
    HostResting,
    ScrapeCanceled,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
)
from .botach import BotachScraper
from .bowman_arms import BowmanArmsScraper
from .capitol_armory import CapitolArmoryScraper
from .centerfire_systems import CenterfireSystemsScraper
from .checkpoint_charlies import CheckpointCharliesScraper
from .cherrys import CherrysScraper
from .cimarron import CimarronScraper
from .classic_firearms import ClassicFirearmsScraper
from .clyde_armory import ClydeArmoryScraper
from .cmp import CmpScraper
from .co_gun_sales import CoGunSalesScraper
from .collectors_firearms import CollectorsFirearmsScraper
from .comers_gunworks import ComersGunworksScraper
from .david_condon import DavidCondonScraper
from .dbg_firearms import DbgFirearmsScraper
from .deleon_rx import DeleonRxScraper
from .demo import DemoScraper
from .dupage_trading import DupageTradingScraper
from .ebayonet import EBayonetScraper
from .empire_arms import EmpireArmsScraper
from .florida_guns import FloridaGunsScraper
from .frisco_guns import FriscoGunsScraper
from .g4g_guns import G4gGunsScraper
from .greentop import GreentopScraper
from .gunprime import GunPrimeScraper
from .horse_soldier import HorseSoldierScraper
from .hunters_lodge import HuntersLodgeScraper
from .ima_usa import ImaUsaScraper
from .james_river_armory import JamesRiverArmoryScraper
from .jg_sales import JgSalesScraper
from .jj_military import JjMilitaryScraper
from .joe_salter import JoeSalterScraper
from .kittery_trading_post import KitteryTradingPostScraper
from .ky_gun_co import KyGunCoScraper
from .langara_arms import LangaraArmsScraper
from .legacy_collectibles import LegacyCollectiblesScraper
from .locked_loaded import LockedLoadedScraper
from .lugerman import LugerManScraper
from .madison_guns import MadisonGunsScraper
from .merz_antiques import MerzAntiquesScraper
from .mile_high_shooting import MileHighShootingScraper
from .military_heritage import MilitaryHeritageScraper
from .mokas_raifus import MokasRaifusScraper
from .muzzle_loaders import MuzzleLoadersScraper
from .nickerson_military import NickersonMilitaryScraper
from .october_country import OctoberCountryScraper
from .officer_store import OfficerStoreScraper
from .old_steel_arsenal import OldSteelArsenalScraper
from .oldguns import OldGunsScraper
from .pre98 import Pre98Scraper
from .primary_arms import PrimaryArmsScraper
from .rainier_arms import RainierArmsScraper
from .recoil_gun_works import RecoilGunWorksScraper
from .royal_tiger import RoyalTigerScraper
from .sarco import SarcoScraper
from .shoot_it import ShootItScraper
from .silencer_central import SilencerCentralScraper
from .simpson_ltd import SimpsonLtdScraper
from .sportsmans_outdoor import SportsmansOutdoorScraper
from .surplus_defense import SurplusDefenseScraper
from .target_sports_usa import TargetSportsUsaScraper
from .the_gun_works import TheGunWorksScraper
from .tortuga_trading import TortugaTradingScraper
from .track_of_the_wolf import TrackOfTheWolfScraper
from .veteran_arms import VeteranArmsScraper
from .we_buy_guns import WeBuyGunsScraper
from .what_a_country import WhatACountryScraper
from .ww2_collectibles import Ww2CollectiblesScraper


def _demo_site_enabled() -> bool:
    """Whether to register the network-free demo scraper.

    Off by default: it is a test fixture, and a real deployment should never
    show a fake vendor in its site list. The end-to-end suite and the
    screenshot runner set this so they can exercise the scan pipeline without
    contacting anyone.
    """
    return os.environ.get("MILSURP_ENABLE_DEMO_SITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


#: Every scraper the application knows about. Order sets the initial UI order.
SCRAPER_CLASSES: tuple[type[SiteScraper], ...] = (
    RoyalTigerScraper,
    EmpireArmsScraper,
    HuntersLodgeScraper,
    CollectorsFirearmsScraper,
    AncestryGunsScraper,
    AxisArmsScraper,
    CoGunSalesScraper,
    CheckpointCharliesScraper,
    LegacyCollectiblesScraper,
    ImaUsaScraper,
    CenterfireSystemsScraper,
    ClassicFirearmsScraper,
    JgSalesScraper,
    SarcoScraper,
    ApexGunPartsScraper,
    ArmsOfAmericaScraper,
    BowmanArmsScraper,
    DupageTradingScraper,
    AtlanticFirearmsScraper,
    *((DemoScraper,) if _demo_site_enabled() else ()),
    RecoilGunWorksScraper,
    OfficerStoreScraper,
    ArmsUnlimitedScraper,
    AimSurplusScraper,
    SurplusDefenseScraper,
    EBayonetScraper,
    GunPrimeScraper,
    JoeSalterScraper,
    SimpsonLtdScraper,
    MadisonGunsScraper,
    DbgFirearmsScraper,
    BotachScraper,
    WhatACountryScraper,
    ClydeArmoryScraper,
    SportsmansOutdoorScraper,
    TargetSportsUsaScraper,
    CmpScraper,
    AlleghenyArsenalScraper,
    Ww2CollectiblesScraper,
    NickersonMilitaryScraper,
    LangaraArmsScraper,
    Pre98Scraper,
    DavidCondonScraper,
    OldGunsScraper,
    HorseSoldierScraper,
    B4AntiquesScraper,
    MerzAntiquesScraper,
    ShootItScraper,
    CherrysScraper,
    LugerManScraper,
    MokasRaifusScraper,
    OldSteelArsenalScraper,
    JjMilitaryScraper,
    KitteryTradingPostScraper,
    WeBuyGunsScraper,
    GreentopScraper,
    MuzzleLoadersScraper,
    TortugaTradingScraper,
    TrackOfTheWolfScraper,
    ComersGunworksScraper,
    TheGunWorksScraper,
    LockedLoadedScraper,
    FloridaGunsScraper,
    G4gGunsScraper,
    FriscoGunsScraper,
    DeleonRxScraper,
    JamesRiverArmoryScraper,
    OctoberCountryScraper,
    AntiqueWeaponStoreScraper,
    CimarronScraper,
    VeteranArmsScraper,
    MilitaryHeritageScraper,
    MileHighShootingScraper,
    RainierArmsScraper,
    CapitolArmoryScraper,
    SilencerCentralScraper,
    KyGunCoScraper,
    PrimaryArmsScraper,
)

_REGISTRY: dict[str, type[SiteScraper]] = {cls.slug: cls for cls in SCRAPER_CLASSES}

if len(_REGISTRY) != len(SCRAPER_CLASSES):  # pragma: no cover - guards a typo
    raise RuntimeError("two scrapers share the same slug")


#: Each shop's own words for a listing with no price, by the name its site
#: row carries, for the shops that have them. See SiteScraper.unpriced_label.
_UNPRICED_LABELS = {cls.name: cls.unpriced_label for cls in SCRAPER_CLASSES if cls.unpriced_label}


def unpriced_label(site_name: str | None) -> str | None:
    """What a listing with no price says, for a shop with words of its own."""
    return _UNPRICED_LABELS.get(site_name or "")


def available_slugs() -> list[str]:
    return list(_REGISTRY)


def get_scraper_class(slug: str) -> type[SiteScraper] | None:
    return _REGISTRY.get(slug)


def get_scraper(slug: str) -> SiteScraper | None:
    cls = _REGISTRY.get(slug)
    return cls() if cls else None


def iter_scrapers() -> list[SiteScraper]:
    return [cls() for cls in SCRAPER_CLASSES]


__all__ = [
    "SCRAPER_CLASSES",
    "Disallowed",
    "HostResting",
    "ScrapeCanceled",
    "ScrapeContext",
    "ScrapeError",
    "ScrapedItem",
    "SiteScraper",
    "available_slugs",
    "get_scraper",
    "get_scraper_class",
    "iter_scrapers",
]
