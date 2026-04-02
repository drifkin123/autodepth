"""Depreciation curve fitting — data prep, floor estimation, and classification.

Contains the pure math/data functions used by the depreciation service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.models.price_prediction import PricePrediction

# Auction sources — only these contribute to curve fitting
AUCTION_SOURCES = {"bring_a_trailer", "cars_and_bids", "rm_sotheby"}

# Minimum confirmed sales needed to attempt curve fitting
MIN_SALES_FOR_FIT = 5

# Natural aspiration floor premium (fraction added on top of base floor)
NA_FLOOR_PREMIUM = 0.20

# Scarcity adjustments based on production count
SCARCITY_TIERS: list[tuple[int | None, float]] = [
    (500,   0.25),
    (2_000, 0.15),
    (10_000, 0.07),
    (None,  0.00),
]

# Base floor as fraction of original MSRP when no production data
BASE_FLOOR_FRACTION = 0.30

# Projection horizon in months
PROJECTION_MONTHS = 36

MODEL_VERSION = "v1"


@dataclass
class FitResult:
    """Output of curve_fit for one car."""
    p0: float
    lam: float
    floor: float
    residual_std: float


def exp_decay(t: np.ndarray, p0: float, lam: float, c: float) -> np.ndarray:
    """P(t) = P0 * exp(-λ * t) + C"""
    return p0 * np.exp(-lam * t) + c


def estimate_floor(car: "Car") -> float:  # noqa: F821
    """Compute the expected price floor as a fraction of original MSRP."""
    fraction = BASE_FLOOR_FRACTION
    for threshold, premium in SCARCITY_TIERS:
        if threshold is None or (car.production_count is not None and car.production_count <= threshold):
            fraction += premium
            break
    if car.is_naturally_aspirated:
        fraction += NA_FLOOR_PREMIUM
    return car.msrp_original * fraction


def months_since_year_start(sale_date: date, year_start: int) -> float:
    """t coordinate: months elapsed since the model's first calendar year."""
    return (sale_date.year - year_start) * 12 + sale_date.month


def prepare_data(
    sales: list,
    year_start: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (t_months, prices) arrays ready for curve fitting.

    Outliers removed via MAD per calendar-month bucket.
    """
    from datetime import datetime

    points: list[tuple[float, float]] = []
    for sale in sales:
        if sale.sold_price is None or sale.sold_at is None:
            continue
        sold_date = sale.sold_at.date() if isinstance(sale.sold_at, datetime) else sale.sold_at
        t = months_since_year_start(sold_date, year_start)
        points.append((t, float(sale.sold_price)))

    if not points:
        return np.array([]), np.array([])

    t_arr = np.array([p[0] for p in points])
    price_arr = np.array([p[1] for p in points])

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


def classify_buy_window(
    fit: FitResult,
    current_t: float,
    reference_date: date,
) -> tuple[str, date | None]:
    """Classify market position using curve slope and second derivative."""
    floor = fit.floor
    current_price = float(exp_decay(np.array([current_t]), fit.p0, fit.lam, floor)[0])
    price_6m_ago = float(exp_decay(np.array([current_t - 6.0]), fit.p0, fit.lam, floor)[0])
    six_month_drop = price_6m_ago - current_price

    first_deriv = -fit.p0 * fit.lam * np.exp(-fit.lam * current_t)
    slope_flat_threshold = current_price * 0.005

    if six_month_drop < -current_price * 0.02:
        return "appreciating", None

    near_floor_threshold = floor * 1.10
    if abs(first_deriv) <= slope_flat_threshold or current_price <= near_floor_threshold:
        if current_price <= near_floor_threshold:
            return "at_floor", reference_date
        return "near_floor", reference_date + timedelta(days=30)

    optimal_buy_date: date | None = None
    for months_ahead in range(1, PROJECTION_MONTHS + 1):
        t_future = current_t + months_ahead
        deriv_future = -fit.p0 * fit.lam * np.exp(-fit.lam * t_future)
        price_future = float(exp_decay(np.array([t_future]), fit.p0, fit.lam, floor)[0])
        threshold_future = price_future * 0.005
        if abs(deriv_future) <= threshold_future:
            optimal_buy_date = reference_date + timedelta(days=months_ahead * 30)
            break

    return "depreciating_fast", optimal_buy_date


def build_predictions(
    car_id: uuid.UUID,
    fit: FitResult,
    reference_date: date,
    current_t: float,
) -> list[PricePrediction]:
    """Build monthly PricePrediction rows for 36 months forward."""
    from datetime import datetime, timezone

    predictions: list[PricePrediction] = []
    now_utc = datetime.now(timezone.utc)

    for months_ahead in range(PROJECTION_MONTHS + 1):
        t = current_t + months_ahead
        predicted = float(exp_decay(np.array([t]), fit.p0, fit.lam, fit.floor)[0])
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
