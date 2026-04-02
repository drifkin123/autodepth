"""Depreciation model service — main entry points."""
from __future__ import annotations

import logging
import uuid
import warnings
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.car import Car
from app.models.price_prediction import PricePrediction
from app.models.vehicle_sale import VehicleSale
from app.services.depreciation_curve import (
    AUCTION_SOURCES, MIN_SALES_FOR_FIT, MODEL_VERSION, FitResult,
    build_predictions, classify_buy_window, estimate_floor,
    exp_decay, months_since_year_start, prepare_data,
)

logger = logging.getLogger(__name__)


@dataclass
class DepreciationResult:
    car_id: uuid.UUID
    fit: FitResult | None
    predictions: list[PricePrediction]
    buy_window_status: str
    buy_window_date: date | None
    summary: str


def _build_summary(
    car: Car,
    status: str,
    buy_window_date: date | None,
    fit: FitResult | None,
) -> str:
    make_model = f"{car.make} {car.model} {car.trim}".strip()

    if fit is None:
        return f"Not enough confirmed sales data to model {make_model} depreciation yet."

    floor_k = int(round(fit.floor / 1000))

    summaries = {
        "at_floor": f"The {make_model} has reached its predicted price floor (~${floor_k}k). "
            "This is the optimal buy zone — values are unlikely to drop further.",
        "near_floor": f"The {make_model} is approaching its predicted floor (~${floor_k}k). "
            "Prices are flattening; consider buying soon or waiting 1–2 months.",
        "appreciating": f"The {make_model} is appreciating — sale prices have been rising. "
            "Waiting is unlikely to save money.",
    }
    if status in summaries:
        return summaries[status]

    if buy_window_date:
        months_away = max(0, (buy_window_date.year - date.today().year) * 12
            + (buy_window_date.month - date.today().month))
        return (f"The {make_model} is still depreciating. Floor (~${floor_k}k) projected "
            f"around {buy_window_date.strftime('%B %Y')} (~{months_away} months). Wait for a deal.")
    return f"The {make_model} is depreciating toward ~${floor_k}k. Floor beyond 36-month horizon."


async def compute_depreciation_result(
    session: AsyncSession,
    car: Car,
    reference_date: date | None = None,
) -> DepreciationResult:
    """Fit the depreciation curve and return results WITHOUT persisting predictions."""
    if reference_date is None:
        reference_date = date.today()

    result = await session.execute(
        select(VehicleSale).where(
            VehicleSale.car_id == car.id,
            VehicleSale.is_sold.is_(True),
            VehicleSale.sold_price.isnot(None),
            VehicleSale.source.in_(AUCTION_SOURCES),
        )
    )
    sales: list[VehicleSale] = list(result.scalars().all())

    def _insufficient(reason: str) -> DepreciationResult:
        logger.info("Car %s (%s %s %s): %s", car.id, car.make, car.model, car.trim, reason)
        return DepreciationResult(
            car_id=car.id, fit=None, predictions=[],
            buy_window_status="depreciating_fast", buy_window_date=None,
            summary=_build_summary(car, "depreciating_fast", None, None),
        )

    if len(sales) < MIN_SALES_FOR_FIT:
        return _insufficient(f"only {len(sales)} confirmed sales — skipping curve fit")

    t_arr, price_arr = prepare_data(sales, car.year_start)

    if len(t_arr) < MIN_SALES_FOR_FIT:
        return _insufficient(f"fewer than {MIN_SALES_FOR_FIT} points after outlier removal")

    estimated_floor = estimate_floor(car)
    current_t = months_since_year_start(reference_date, car.year_start)

    p0_guess = float(price_arr.max()) - estimated_floor
    lam_guess = 0.02
    c_guess = estimated_floor

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, _ = curve_fit(
                exp_decay, t_arr, price_arr,
                p0=[p0_guess, lam_guess, c_guess],
                bounds=(
                    [0, 1e-6, estimated_floor * 0.5],
                    [price_arr.max() * 3, 1.0, estimated_floor * 2.0],
                ),
                maxfev=10_000,
            )
    except (RuntimeError, ValueError) as exc:
        logger.warning("Curve fit failed for car %s: %s", car.id, exc)
        return _insufficient(f"curve fit failed: {exc}")

    p0_fit, lam_fit, c_fit = popt
    residuals = price_arr - exp_decay(t_arr, p0_fit, lam_fit, c_fit)
    residual_std = float(np.std(residuals))

    fit = FitResult(p0=float(p0_fit), lam=float(lam_fit), floor=float(c_fit), residual_std=residual_std)
    buy_status, buy_window_date = classify_buy_window(fit, current_t, reference_date)
    predictions = build_predictions(car.id, fit, reference_date, current_t)
    summary = _build_summary(car, buy_status, buy_window_date, fit)

    logger.info(
        "Car %s (%s %s %s): fit P0=%.0f λ=%.4f floor=%.0f status=%s",
        car.id, car.make, car.model, car.trim, p0_fit, lam_fit, c_fit, buy_status,
    )

    return DepreciationResult(
        car_id=car.id, fit=fit, predictions=predictions,
        buy_window_status=buy_status, buy_window_date=buy_window_date, summary=summary,
    )


async def run_depreciation_model(
    session: AsyncSession,
    car: Car,
    reference_date: date | None = None,
) -> DepreciationResult:
    """Fit curve for a single car and persist predictions."""
    result = await compute_depreciation_result(session, car, reference_date)

    if result.predictions:
        await session.execute(
            delete(PricePrediction).where(
                PricePrediction.car_id == car.id,
                PricePrediction.model_version == MODEL_VERSION,
            )
        )
        session.add_all(result.predictions)
        await session.commit()

    return result


async def run_all_depreciation_models(session: AsyncSession) -> dict[str, str]:
    """Run the depreciation model for every car in the catalog."""
    result = await session.execute(select(Car))
    cars: list[Car] = list(result.scalars().all())

    statuses: dict[str, str] = {}
    for car in cars:
        try:
            dep = await run_depreciation_model(session, car)
            statuses[str(car.id)] = dep.buy_window_status
        except Exception:
            logger.exception("Depreciation model failed for car %s", car.id)
            statuses[str(car.id)] = "error"

    return statuses
