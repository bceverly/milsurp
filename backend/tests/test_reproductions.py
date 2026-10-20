"""Whether a listing reads as a reproduction (app.services.reproductions).

Each phrase is production's, from 2026-10-19 and 2026-10-20: the copies the
C&R reader and the serial dating had taken for the old gun, and the originals
a first draft took for copies.
"""

from __future__ import annotations

import pytest

from app.services import curio
from app.services.reproductions import is_reproduction


@pytest.mark.parametrize(
    "text",
    [
        "Pietta 1851 Sheriff",
        "Minty, Boxed Uberti 1872 Open Top Late Model Revolver",
        "Taylor's & Company 1860 Henry is a faithful full-size reproduction",
        "The Mountain rifle has been created to replicate the Hawken of the 1840's",
        "TIPPMANN ARMS CO 1919A4 MINIATURE 1/2 SCALE, .22LR SEMI AUTO",
        "31356-EXCELLENT REPRODUCTION CIVIL WAR CSA CONFEDERATE RICHMOND MODEL",
        "Colt Single Action Army 47% Scale Non-Firing Miniature Replica Revolver",
        "with a blued round barrel and the notorious Uberti blue finish",
        "the company's reproduction of the Springfield Officer's Model trapdoor",
        "It is also possible it is a very good reproduction.",
    ],
)
def test_a_copy(text):
    assert is_reproduction(text)


@pytest.mark.parametrize(
    "text",
    [
        "FULLY FUNCTIONING SPLIT BREECH ACTION, NOT A REPRODUCTION",
        "This is a legitimate antique and not a reproduction.",
        "authentic antique military rifles rather than newly manufactured reproductions",
        "In the 1940s, Portugal received K98k replicas, similar to the 1941 K98k",
        "Heck, the reproductions from Inland are nearly $1400.",
        "Fitted with reproduction black plastic grips.",
        "comes with a reproduction P.38 holster and spare magazine",
        "M1D build up. Reproduction base and mount.",
        "AND A REPRO MANUAL.",
        "with FREE Reproduction Sling and Oiler",
        "Rossi Garrucha Double Derringer .22 LR",
        "J.H. Johnston's Great Western Gun Works was located just down the street",
        "owners manual (repro), a spare magazine, and Walther cleaning rod",
        "Original base. Mount is a possible reproduction. DRC T105 rear sight.",
        "Flattop walnut handguard is reproduction. The bore has corrosion throughout.",
        "Please note that it has a reproduction safety lever.",
        "This is not a molded replica, lightweight reproduction, or theatrical prop.",
        "These modified Krag Carbines resembled miniature Krag rifles.",
        "a .22 LR training pistol that closely replicated the look of the service pistol",
        "Manufactured in 1960. With reproduction Colt black box numbered to gun.",
        "Some repro G&H mounts have been made which are nice",
        "the scope can is matching but appears to be a reproduction",
        "later High Standard Manufacturing of Houston, Texas, acquired the business",
        "the classic pre-Miroku craftsmanship that defines the golden era",
    ],
)
def test_an_original(text):
    assert not is_reproduction(text)


def test_the_c_and_r_reader_gives_a_copy_no_year():
    """ "Pietta 1858 New Army" was eligible by age, from its pattern's year."""
    assert curio.read("Pietta 1858 New Army Revolver .44").year is None
    assert curio.read("Colt 1858 revolver, made in 1858").year == 1858
    # The shop's own word still decides.
    assert curio.read("Uberti 1873 Cattleman, not C&R").stated is False
