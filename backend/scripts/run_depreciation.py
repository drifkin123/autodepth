"""Run depreciation model manually.

Usage from backend/:
    # Run for all cars
    python scripts/run_depreciation.py

    # Run for a single car by UUID
    python scripts/run_depreciation.py --car-id <uuid>
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import uuid

from sqlalchemy import select

from app.db import async_session_factory
from app.models.car import Car
from app.services.depreciation import run_all_depreciation_models, run_depreciation_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main(car_id: str | None) -> None:
    async with async_session_factory() as session:
        if car_id:
            try:
                parsed_id = uuid.UUID(car_id)
            except ValueError:
                print(f"Invalid UUID: {car_id}")
                sys.exit(1)
            result = await session.execute(select(Car).where(Car.id == parsed_id))
            car = result.scalar_one_or_none()
            if car is None:
                print(f"Car not found: {car_id}")
                sys.exit(1)
            dep = await run_depreciation_model(session, car)
            print(f"{car.make} {car.model} {car.trim}: {dep.buy_window_status}")
            print(f"  {dep.summary}")
            if dep.fit:
                print(
                    f"  P0={dep.fit.p0:.0f}  λ={dep.fit.lam:.4f}  "
                    f"floor={dep.fit.floor:.0f}  residual_std={dep.fit.residual_std:.0f}"
                )
            print(f"  predictions generated: {len(dep.predictions)}")
        else:
            statuses = await run_all_depreciation_models(session)
            for cid, status in statuses.items():
                print(f"{cid}: {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--car-id", help="Run model for a single car UUID")
    args = parser.parse_args()
    asyncio.run(main(args.car_id))
