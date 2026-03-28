"""Depreciation model service.

Fits an exponential decay curve P(t) = P0 * e^(-λt) + C to confirmed auction
sold prices, projects 36 months forward, and classifies the current buy window.

Time convention
---------------
t is measured in months since the car model's year_start (e.g. a 2019 car has
t ≈ 12 at its first birthday). Older cars have larger t, so P(t) naturally
decreases as t grows — matching the formula's intent.

Only sold_price from auction sources is used for curve fitting. Listing/asking
prices are never mixed into the model.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.car import Car
from app.models.price_prediction import PricePrediction
from app.models.vehicle_sale import VehicleSale

logger = logging.getLogger(__name__)

MODEL_VERSION = "v1"

# Auction sources — only these contribute to curve fitting
AUCTION_SOURCES = {"bring_a_trailer", "cars_and_bids", "rm_sotheby"}

# Minimum confirmed sales needed to attempt curve fitting
MIN_SALES_FOR_FIT = 5

# Natural aspiration floor premium (fraction added on top of base floor)
NA_FLOOR_PREMIUM = 0.20

# Scarcity adjustments based on production count
# production_count → added fraction of MSRP for floor
SCARCITY_TIERS: list[tuple[int | None, float]] = [
    (500,   0.25),  # very limited: ≤500 units
    (2_000, 0.15),  # limited: ≤2 000 units
    (10_000, 0.07), # uncommon: ≤10 000 units
    (None,  0.00),  # common: no premium
]

# Base floor as fraction of original MSRP when no production data
BASE_FLOOR_FRACTION = 0.30

# Projection horizon in months
PROJECTION_MONTHS = 36


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class FitResult:
    """Output of curve_fit for one car."""
    p0: float       # initial price intercept (at t=0)
    lam: float      # decay rate (per month)
    floor: float    # asymptotic floor price
    residual_std: float


@dataclass
class DepreciationResult:
    car_id: uuid.UUID
    fit: FitResult | None          # None when insufficient data
    predictions: list[PricePrediction]
    buy_window_status: str
    buy_window_date: date | None
    summary: str


# ─── Curve model ──────────────────────────────────────────────────────────────

def _exp_decay(t: np.ndarray, p0: float, lam: float, c: float) -> np.ndarray:
    """P(t) = P0 * exp(-λ * t) + C

    t = months since the car model's year_start.
    As t grows (car ages), price falls toward floor C.
    """
    return p0 * np.exp(-lam * t) + c


# ─── Floor estimation ─────────────────────────────────────────────────────────

def _estimate_floor(car: Car) -> float:
    """Compute the expected price floor as a fraction of original MSRP."""
    fraction = BASE_FLOOR_FRACTION

    # Scarcity premium
    for threshold, premium in SCARCITY_TIERS:
        if threshold is None or (car.production_count is not None and car.production_count <= threshold):
            fraction += premium
            break

    # Natural aspiration premium
    if car.is_naturally_aspirated:
        fraction += NA_FLOOR_PREMIUM

    return car.msrp_original * fraction


# ─── Data preparation ─────────────────────────────────────────────────────────

def _months_since_year_start(sale_date: date, year_start: int) -> float:
    """t coordinate: months elapsed since the model's first calendar year."""
    return (sale_date.year - year_start) * 12 + sale_date.month


def _prepare_data(
    sales: list[VehicleSale],
    year_start: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (t_months, prices) arrays ready for curve fitting.

    t_months: months since year_start (larger = older car / further into the future)
    prices: confirmed sold_price in USD

    Outliers are detected per calendar-month bucket using Median Absolute
    Deviation (MAD), which is robust to the outlier inflating the spread.
    Points more than 3 * scaled_MAD from the bucket median are removed.
    """
    points: list[tuple[float, float]] = []

    for sale in sales:
        if sale.sold_price is None or sale.sold_at is None:
            continue
        sold_date = sale.sold_at.date() if isinstance(sale.sold_at, datetime) else sale.sold_at
        t = _months_since_year_start(sold_date, year_start)
        points.append((t, float(sale.sold_price)))

    if not points:
        return np.array([]), np.array([])

    t_arr = np.array([p[0] for p in points])
    price_arr = np.array([p[1] for p in points])

    # Outlier removal using MAD per calendar-month bucket
    keep = np.ones(len(t_arr), dtype=bool)
    unique_months = np.unique(t_arr.astype(int))
    for m in unique_months:
        mask = t_arr.astype(int) == m
        bucket_prices = price_arr[mask]
        if len(bucket_prices) < 3:
            continue
        median = np.median(bucket_prices)
        mad = np.median(np.abs(bucket_prices - median))
        scaled_mad = 1.4826 * mad
        if scaled_mad == 0:
            continue
        outlier_mask = mask & (np.abs(price_arr - median) > 3 * scaled_mad)
        keep[outlier_mask] = False

    return t_arr[keep], price_arr[keep]


# ─── Buy window classification ────────────────────────────────────────────────

def _classify_buy_window(
    fit: FitResult,
    current_t: float,
    reference_date: date,
) -> tuple[str, date | None]:
    """
    Classify the current market position using curve slope and second derivative.

    current_t: age of the car in months right now (months since year_start).

    Returns (status, optimal_buy_date).
    """
    floor = fit.floor

    current_price = float(_exp_decay(np.array([current_t]), fit.p0, fit.lam, floor)[0])

    # Price 6 months ago = car was 6 months younger → t was smaller
    price_6m_ago = float(_exp_decay(np.array([current_t - 6.0]), fit.p0, fit.lam, floor)[0])
    six_month_drop = price_6m_ago - current_price  # positive = prices fell (normal depreciation)

    # First derivative at current_t: dP/dt = -P0 * λ * e^(-λt)
    first_deriv = -fit.p0 * fit.lam * np.exp(-fit.lam * current_t)

    # Threshold: slope is "flat" when monthly drop < 0.5% of current price
    slope_flat_threshold = current_price * 0.005

    # Appreciating: price rose over the last 6 months (six_month_drop < 0 and meaningful)
    if six_month_drop < -current_price * 0.02:
        return "appreciating", None

    # At/near floor: slope nearly flat OR price within 10% of estimated floor
    near_floor_threshold = floor * 1.10
    if abs(first_deriv) <= slope_flat_threshold or current_price <= near_floor_threshold:
        if current_price <= near_floor_threshold:
            return "at_floor", reference_date
        return "near_floor", reference_date + timedelta(days=30)

    # Still depreciating — find the projected month when slope flattens
    optimal_buy_date: date | None = None
    for months_ahead in range(1, PROJECTION_MONTHS + 1):
        t_future = current_t + months_ahead
        deriv_future = -fit.p0 * fit.lam * np.exp(-fit.lam * t_future)
        price_future = float(_exp_decay(np.array([t_future]), fit.p0, fit.lam, floor)[0])
        threshold_future = price_future * 0.005
        if abs(deriv_future) <= threshold_future:
            optimal_buy_date = reference_date + timedelta(days=months_ahead * 30)
            break

    return "depreciating_fast", optimal_buy_date


# ─── Prediction generation ────────────────────────────────────────────────────

def _build_predictions(
    car_id: uuid.UUID,
    fit: FitResult,
    reference_date: date,
    current_t: float,
) -> list[PricePrediction]:
    """Build monthly PricePrediction rows for 36 months forward."""
    predictions: list[PricePrediction] = []
    now_utc = datetime.now(timezone.utc)

    for months_ahead in range(PROJECTION_MONTHS + 1):
        t = current_t + months_ahead
        predicted = float(_exp_decay(np.array([t]), fit.p0, fit.lam, fit.floor)[0])
        lo = max(predicted - fit.residual_std, 0.0)
        hi = predicted + fit.residual_std

        target_date = (
            date(reference_date.year, reference_date.month, 1)
            + timedelta(days=months_ahead * 31)
        ).replace(day=1)

        predictions.append(
            PricePrediction(
                id=uuid.uuid4(),
                car_id=car_id,
                model_version=MODEL_VERSION,
                predicted_for=target_date,
                predicted_price=int(round(predicted)),
                confidence_low=int(round(lo)),
                confidence_high=int(round(hi)),
                generated_at=now_utc,
            )
        )

    return predictions


# ─── Plain-English summary ────────────────────────────────────────────────────

def _build_summary(
    car: Car,
    status: str,
    buy_window_date: date | None,
    fit: FitResult | None,
) -> str:
    make_model = f"{car.make} {car.model} {car.trim}".strip()

    if fit is None:
        return (
            f"Not enough confirmed sales data to model {make_model} depreciation yet. "
            "Check back after more auction results are collected."
        )

    floor_k = int(round(fit.floor / 1000))

    if status == "at_floor":
        return (
            f"The {make_model} has reached its predicted price floor (~${floor_k}k). "
            "This is the optimal buy zone — values are unlikely to drop meaningfully further."
        )
    if status == "near_floor":
        return (
            f"The {make_model} is approaching its predicted floor (~${floor_k}k). "
            "Prices are flattening; consider buying soon or waiting 1–2 months for the bottom."
        )
    if status == "appreciating":
        return (
            f"The {make_model} is appreciating — confirmed sale prices have been rising. "
            "This car may be entering collectible territory; waiting is unlikely to save money."
        )
    # depreciating_fast
    if buy_window_date:
        months_away = max(
            0,
            (buy_window_date.year - date.today().year) * 12
            + (buy_window_date.month - date.today().month),
        )
        return (
            f"The {make_model} is still depreciating. The model projects the price floor "
            f"(~${floor_k}k) around {buy_window_date.strftime('%B %Y')} "
            f"(~{months_away} month{'s' if months_away != 1 else ''} from now). "
            "Consider waiting unless you find an exceptional deal."
        )
    return (
        f"The {make_model} is still depreciating toward a predicted floor of ~${floor_k}k. "
        "The floor is projected beyond the 36-month horizon."
    )


# ─── Main entry points ────────────────────────────────────────────────────────

async def compute_depreciation_result(
    session: AsyncSession,
    car: Car,
    reference_date: date | None = None,
) -> DepreciationResult:
    """
    Fit the depreciation curve and return results WITHOUT persisting predictions.
    Use this for read-only API endpoints; use run_depreciation_model to also persist.
    """
    if reference_date is None:
        reference_date = date.today()

    # Load confirmed auction sales only
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
            car_id=car.id,
            fit=None,
            predictions=[],
            buy_window_status="depreciating_fast",
            buy_window_date=None,
            summary=_build_summary(car, "depreciating_fast", None, None),
        )

    if len(sales) < MIN_SALES_FOR_FIT:
        return _insufficient(f"only {len(sales)} confirmed sales — skipping curve fit")

    t_arr, price_arr = _prepare_data(sales, car.year_start)

    if len(t_arr) < MIN_SALES_FOR_FIT:
        return _insufficient(f"fewer than {MIN_SALES_FOR_FIT} points after outlier removal")

    estimated_floor = _estimate_floor(car)

    # current_t: age of the car right now (months since year_start)
    current_t = _months_since_year_start(reference_date, car.year_start)

    # Initial parameter guesses
    p0_guess = float(price_arr.max()) - estimated_floor
    lam_guess = 0.02  # ~2% decay per month
    c_guess = estimated_floor

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, _ = curve_fit(
                _exp_decay,
                t_arr,
                price_arr,
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
    residuals = price_arr - _exp_decay(t_arr, p0_fit, lam_fit, c_fit)
    residual_std = float(np.std(residuals))

    fit = FitResult(p0=float(p0_fit), lam=float(lam_fit), floor=float(c_fit), residual_std=residual_std)
    status, buy_window_date = _classify_buy_window(fit, current_t, reference_date)
    predictions = _build_predictions(car.id, fit, reference_date, current_t)
    summary = _build_summary(car, status, buy_window_date, fit)

    logger.info(
        "Car %s (%s %s %s): fit P0=%.0f λ=%.4f floor=%.0f status=%s",
        car.id, car.make, car.model, car.trim, p0_fit, lam_fit, c_fit, status,
    )

    return DepreciationResult(
        car_id=car.id,
        fit=fit,
        predictions=predictions,
        buy_window_status=status,
        buy_window_date=buy_window_date,
        summary=summary,
    )


async def run_depreciation_model(
    session: AsyncSession,
    car: Car,
    reference_date: date | None = None,
) -> DepreciationResult:
    """
    Fit the depreciation curve for a single car and persist predictions.

    Deletes any existing predictions for this car+model_version before writing new ones.
    """
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
    """
    Run the depreciation model for every car in the catalog.
    Returns {car_id_str: buy_window_status}.
    """
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
