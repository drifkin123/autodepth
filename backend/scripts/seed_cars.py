"""Seed the cars catalog.

Run from the backend/ directory:
    python scripts/seed_cars.py
"""

import asyncio
import sys
from pathlib import Path

# Make app importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.models.car import Car

# ---------------------------------------------------------------------------
# Catalog data
# Each entry: (make, model, trim, year_start, year_end, production_count,
#              engine, is_naturally_aspirated, msrp_original, notes)
# ---------------------------------------------------------------------------
CARS: list[dict] = [
    # ── Porsche ──────────────────────────────────────────────────────────────
    dict(
        make="Porsche", model="911", trim="GT3 (996)",
        year_start=1999, year_end=2005, production_count=None,
        engine="3.6L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=90000, notes="First modern GT3; air-cooled successor spirit",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 (997)",
        year_start=2007, year_end=2009, production_count=None,
        engine="3.6L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=104300, notes="997.1 GT3; last with Mezger-derived engine",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 (991)",
        year_start=2014, year_end=2019, production_count=None,
        engine="4.0L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=130400, notes="991.1 & 991.2 GT3; PDK-only from 991.2",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 (992)",
        year_start=2022, year_end=None, production_count=None,
        engine="4.0L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=161100, notes="992 GT3; manual or PDK",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 RS (997)",
        year_start=2007, year_end=2011, production_count=None,
        engine="3.8L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=152900, notes="997 GT3 RS; aero-focused track weapon",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 RS (991)",
        year_start=2016, year_end=2020, production_count=None,
        engine="4.0L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=176400, notes="991.2 GT3 RS; magnesium roof",
    ),
    dict(
        make="Porsche", model="911", trim="GT3 RS (992)",
        year_start=2023, year_end=None, production_count=None,
        engine="4.0L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=223800, notes="992 GT3 RS; DRS wing",
    ),
    dict(
        make="Porsche", model="911", trim="Turbo S (991)",
        year_start=2014, year_end=2019, production_count=None,
        engine="3.8L Twin-Turbo Flat-6", is_naturally_aspirated=False,
        msrp_original=188100, notes="991.2 Turbo S; 580 hp",
    ),
    dict(
        make="Porsche", model="911", trim="Turbo S (992)",
        year_start=2021, year_end=None, production_count=None,
        engine="3.8L Twin-Turbo Flat-6", is_naturally_aspirated=False,
        msrp_original=203500, notes="992 Turbo S; 640 hp",
    ),
    dict(
        make="Porsche", model="Cayman", trim="GT4 (981)",
        year_start=2016, year_end=2016, production_count=None,
        engine="3.8L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=84600, notes="981 Cayman GT4; manual only, instant classic",
    ),
    dict(
        make="Porsche", model="Cayman", trim="GT4 (982)",
        year_start=2020, year_end=None, production_count=None,
        engine="4.0L NA Flat-6", is_naturally_aspirated=True,
        msrp_original=99200, notes="982 Cayman GT4; shared engine with 992 GT3",
    ),
    dict(
        make="Porsche", model="918", trim="Spyder",
        year_start=2013, year_end=2015, production_count=918,
        engine="4.6L NA V8 + 2 electric motors", is_naturally_aspirated=True,
        msrp_original=845000,
        notes="Hybrid hypercar; Weissach package adds significant value",
    ),

    # ── Ferrari ───────────────────────────────────────────────────────────────
    dict(
        make="Ferrari", model="458", trim="Italia",
        year_start=2010, year_end=2015, production_count=None,
        engine="4.5L NA V8", is_naturally_aspirated=True,
        msrp_original=230000, notes="Last naturally aspirated Ferrari mid-engine V8",
    ),
    dict(
        make="Ferrari", model="458", trim="Spider",
        year_start=2012, year_end=2015, production_count=None,
        engine="4.5L NA V8", is_naturally_aspirated=True,
        msrp_original=263000, notes="Open-top 458; retractable hardtop",
    ),
    dict(
        make="Ferrari", model="458", trim="Speciale",
        year_start=2014, year_end=2015, production_count=3799,
        engine="4.5L NA V8", is_naturally_aspirated=True,
        msrp_original=291744, notes="Limited track-focused 458; values appreciating",
    ),
    dict(
        make="Ferrari", model="488", trim="GTB",
        year_start=2015, year_end=2019, production_count=None,
        engine="3.9L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=245400, notes="First turbocharged mid-engine Ferrari since F40",
    ),
    dict(
        make="Ferrari", model="488", trim="Pista",
        year_start=2018, year_end=2020, production_count=None,
        engine="3.9L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=350000, notes="Track-focused 488; 711 hp",
    ),
    dict(
        make="Ferrari", model="F8", trim="Tributo",
        year_start=2020, year_end=2022, production_count=None,
        engine="3.9L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=276550, notes="Final iteration of 488 platform",
    ),
    dict(
        make="Ferrari", model="F8", trim="Spider",
        year_start=2020, year_end=2022, production_count=None,
        engine="3.9L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=309870, notes="Convertible F8 Tributo",
    ),
    dict(
        make="Ferrari", model="SF90", trim="Stradale",
        year_start=2021, year_end=None, production_count=None,
        engine="4.0L Twin-Turbo V8 + 3 electric motors", is_naturally_aspirated=False,
        msrp_original=507000, notes="Ferrari's first series production PHEV; 986 hp",
    ),
    dict(
        make="Ferrari", model="Roma", trim="Coupe",
        year_start=2021, year_end=None, production_count=None,
        engine="3.9L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=222620, notes="GT-oriented; 2+ seater coupe",
    ),

    # ── Lamborghini ───────────────────────────────────────────────────────────
    dict(
        make="Lamborghini", model="Huracán", trim="LP610-4",
        year_start=2014, year_end=2016, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=237250, notes="Base Huracán; 610 hp AWD",
    ),
    dict(
        make="Lamborghini", model="Huracán", trim="Performante",
        year_start=2018, year_end=2021, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=274390, notes="Nürburgring record holder at launch; forged carbon",
    ),
    dict(
        make="Lamborghini", model="Huracán", trim="EVO",
        year_start=2019, year_end=2022, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=261274, notes="Updated chassis dynamics; AWD and RWD variants",
    ),
    dict(
        make="Lamborghini", model="Huracán", trim="STO",
        year_start=2021, year_end=2024, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=327838, notes="Super Trofeo Omologata; road-legal race car",
    ),
    dict(
        make="Lamborghini", model="Urus", trim="Base",
        year_start=2019, year_end=2022, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=218009, notes="Super SUV; outsells all other Lamborghinis combined",
    ),
    dict(
        make="Lamborghini", model="Urus", trim="S",
        year_start=2023, year_end=None, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=238459, notes="Updated Urus with more power and revised interior",
    ),
    dict(
        make="Lamborghini", model="Aventador", trim="S",
        year_start=2017, year_end=2021, production_count=None,
        engine="6.5L NA V12", is_naturally_aspirated=True,
        msrp_original=417650, notes="Naturally aspirated V12; visceral and analog",
    ),
    dict(
        make="Lamborghini", model="Aventador", trim="SVJ",
        year_start=2019, year_end=2022, production_count=900,
        engine="6.5L NA V12", is_naturally_aspirated=True,
        msrp_original=573546,
        notes="Superveloce Jota; 770 hp, ALA 2.0 aero, Nürburgring record",
    ),

    # ── McLaren ───────────────────────────────────────────────────────────────
    dict(
        make="McLaren", model="570S", trim="Coupe",
        year_start=2016, year_end=2021, production_count=None,
        engine="3.8L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=191640, notes="Sports Series entry; Track Pack popular option",
    ),
    dict(
        make="McLaren", model="600LT", trim="Coupe",
        year_start=2018, year_end=2020, production_count=None,
        engine="3.8L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=240000, notes="Longtail 570S; top-exit exhausts, fixed rear wing",
    ),
    dict(
        make="McLaren", model="720S", trim="Coupe",
        year_start=2018, year_end=2023, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=299000, notes="Super Series; dihedral doors, class-leading dynamics",
    ),
    dict(
        make="McLaren", model="765LT", trim="Coupe",
        year_start=2021, year_end=2022, production_count=765,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=358000, notes="Longtail 720S; 765 hp, lightweight, highly collectible",
    ),
    dict(
        make="McLaren", model="Artura", trim="Base",
        year_start=2023, year_end=None, production_count=None,
        engine="3.0L Twin-Turbo V6 + electric motor", is_naturally_aspirated=False,
        msrp_original=237000, notes="First McLaren PHEV; new carbon architecture",
    ),

    # ── Mercedes-AMG ─────────────────────────────────────────────────────────
    dict(
        make="Mercedes-AMG", model="AMG GT", trim="Base",
        year_start=2016, year_end=2021, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=130000, notes="Front-engine GT; transaxle layout",
    ),
    dict(
        make="Mercedes-AMG", model="AMG GT", trim="S",
        year_start=2016, year_end=2021, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=142400, notes="503 hp AMG GT S",
    ),
    dict(
        make="Mercedes-AMG", model="AMG GT", trim="R",
        year_start=2017, year_end=2021, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=162900, notes="GT R; rear-wheel steering, active aero",
    ),
    dict(
        make="Mercedes-AMG", model="AMG GT 63 S", trim="4-Door",
        year_start=2019, year_end=None, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=161400, notes="4-door coupe; 630 hp practical performance",
    ),

    # ── Audi ─────────────────────────────────────────────────────────────────
    dict(
        make="Audi", model="R8", trim="V10 (Gen 1)",
        year_start=2007, year_end=2015, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=155000, notes="Gen 1 R8 V10; naturally aspirated soundtrack",
    ),
    dict(
        make="Audi", model="R8", trim="V10 (Gen 2)",
        year_start=2016, year_end=2023, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=169900, notes="Gen 2 R8; virtual cockpit, 540 hp",
    ),
    dict(
        make="Audi", model="R8", trim="V10 Performance",
        year_start=2020, year_end=2023, production_count=None,
        engine="5.2L NA V10", is_naturally_aspirated=True,
        msrp_original=196900, notes="Final R8 variant; 602 hp, last NA Audi",
    ),
    dict(
        make="Audi", model="RS6", trim="Avant (C8)",
        year_start=2021, year_end=None, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=117900, notes="C8 RS6 Avant; 591 hp estate wagon",
    ),
    dict(
        make="Audi", model="RS7", trim="Sportback (C8)",
        year_start=2021, year_end=None, production_count=None,
        engine="4.0L Twin-Turbo V8", is_naturally_aspirated=False,
        msrp_original=117900, notes="C8 RS7; fastback body, same drivetrain as RS6",
    ),

    # ── Chevrolet ─────────────────────────────────────────────────────────────
    dict(
        make="Chevrolet", model="Corvette", trim="C8 Stingray",
        year_start=2020, year_end=None, production_count=None,
        engine="6.2L NA V8", is_naturally_aspirated=True,
        msrp_original=59995, notes="First mid-engine Corvette; massive value proposition",
    ),
    dict(
        make="Chevrolet", model="Corvette", trim="C8 Z06",
        year_start=2023, year_end=None, production_count=None,
        engine="5.5L NA Flat-Plane V8", is_naturally_aspirated=True,
        msrp_original=106395,
        notes="Flat-plane crank V8; 670 hp NA, screams to 8600 rpm",
    ),
    dict(
        make="Chevrolet", model="Corvette", trim="C8 E-Ray",
        year_start=2024, year_end=None, production_count=None,
        engine="6.2L NA V8 + electric front motor", is_naturally_aspirated=True,
        msrp_original=104295, notes="Hybrid AWD Corvette; 655 hp",
    ),

    # ── Lotus ─────────────────────────────────────────────────────────────────
    dict(
        make="Lotus", model="Emira", trim="V6",
        year_start=2023, year_end=None, production_count=None,
        engine="3.5L Supercharged V6", is_naturally_aspirated=False,
        msrp_original=93900, notes="Last ICE Lotus; supercharged Toyota V6",
    ),
    dict(
        make="Lotus", model="Evora", trim="GT",
        year_start=2020, year_end=2022, production_count=None,
        engine="3.5L Supercharged V6", is_naturally_aspirated=False,
        msrp_original=96950, notes="Final Evora; driver-focused mid-engine GT",
    ),
    dict(
        make="Lotus", model="Exige", trim="S",
        year_start=2012, year_end=2021, production_count=None,
        engine="3.5L Supercharged V6", is_naturally_aspirated=False,
        msrp_original=75900, notes="Track-focused lightweight; supercharged V6",
    ),
    dict(
        make="Lotus", model="Exige", trim="Cup 430",
        year_start=2017, year_end=2021, production_count=None,
        engine="3.5L Supercharged V6", is_naturally_aspirated=False,
        msrp_original=112900, notes="Most extreme road-legal Exige; 430 hp, 2050 lbs",
    ),
]


async def seed(session: AsyncSession) -> None:
    inserted = 0
    skipped = 0
    for data in CARS:
        existing = await session.execute(
            select(Car).where(
                Car.make == data["make"],
                Car.model == data["model"],
                Car.trim == data["trim"],
            )
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        car = Car(**data)
        session.add(car)
        inserted += 1

    await session.commit()
    print(f"Seed complete: {inserted} inserted, {skipped} already existed.")


async def main() -> None:
    async with async_session_factory() as session:
        await seed(session)


if __name__ == "__main__":
    asyncio.run(main())
