"""Unit tests for the depreciation model service.

These tests do NOT require a database — they exercise the pure-Python
curve fitting and classification logic directly.

Time convention: t = months since the car model's year_start.
Larger t = older car = more depreciated = lower price.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.services.depreciation import (
    BASE_FLOOR_FRACTION,
    FitResult,
    NA_FLOOR_PREMIUM,
    _build_summary,
    _classify_buy_window,
    _estimate_floor,
    _exp_decay,
    _months_since_year_start,
    _prepare_data,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_car(
    *,
    msrp: int = 200_000,
    production_count: int | None = None,
    is_naturally_aspirated: bool = False,
    make: str = "Porsche",
    model: str = "911 GT3",
    trim: str = "RS",
    year_start: int = 2019,
) -> MagicMock:
    car = MagicMock()
    car.id = uuid.uuid4()
    car.make = make
    car.model = model
    car.trim = trim
    car.msrp_original = msrp
    car.production_count = production_count
    car.is_naturally_aspirated = is_naturally_aspirated
    car.year_start = year_start
    return car


def _make_sale(
    *,
    sold_price: int,
    sold_year: int,
    sold_month: int = 6,
    source: str = "bring_a_trailer",
) -> MagicMock:
    sold_at = datetime(sold_year, sold_month, 15, tzinfo=timezone.utc)
    sale = MagicMock()
    sale.sold_price = sold_price
    sale.sold_at = sold_at
    sale.source = source
    sale.is_sold = True
    return sale


# ─── _exp_decay ───────────────────────────────────────────────────────────────

class TestExpDecay:
    def test_at_t0_equals_p0_plus_floor(self) -> None:
        result = _exp_decay(np.array([0.0]), 100_000, 0.02, 50_000)
        assert abs(result[0] - 150_000) < 1

    def test_approaches_floor_at_large_t(self) -> None:
        result = _exp_decay(np.array([1_000.0]), 100_000, 0.5, 50_000)
        assert abs(result[0] - 50_000) < 0.01

    def test_monotonically_decreasing_for_positive_lam(self) -> None:
        t = np.linspace(0, 100, 200)
        prices = _exp_decay(t, 100_000, 0.05, 30_000)
        diffs = np.diff(prices)
        assert np.all(diffs <= 0)


# ─── _months_since_year_start ─────────────────────────────────────────────────

class TestMonthsSinceYearStart:
    def test_same_year_returns_month(self) -> None:
        assert _months_since_year_start(date(2019, 3, 1), 2019) == 3.0

    def test_one_year_later(self) -> None:
        assert _months_since_year_start(date(2020, 1, 1), 2019) == 13.0

    def test_recent_car_has_larger_t(self) -> None:
        t_old = _months_since_year_start(date(2020, 1, 1), 2019)
        t_new = _months_since_year_start(date(2022, 1, 1), 2019)
        assert t_new > t_old


# ─── _estimate_floor ──────────────────────────────────────────────────────────

class TestEstimateFloor:
    def test_base_floor_no_premium(self) -> None:
        car = _make_car(msrp=200_000, production_count=50_000, is_naturally_aspirated=False)
        floor = _estimate_floor(car)
        assert floor == 200_000 * BASE_FLOOR_FRACTION

    def test_na_premium_added(self) -> None:
        car_base = _make_car(msrp=200_000, production_count=50_000, is_naturally_aspirated=False)
        car_na = _make_car(msrp=200_000, production_count=50_000, is_naturally_aspirated=True)
        floor_base = _estimate_floor(car_base)
        floor_na = _estimate_floor(car_na)
        assert floor_na == floor_base + 200_000 * NA_FLOOR_PREMIUM

    def test_scarcity_premium_very_limited(self) -> None:
        car_common = _make_car(msrp=200_000, production_count=50_000)
        car_rare = _make_car(msrp=200_000, production_count=300)
        assert _estimate_floor(car_rare) > _estimate_floor(car_common)

    def test_scarcity_premium_limited(self) -> None:
        car_uncommon = _make_car(msrp=200_000, production_count=5_000)
        car_limited = _make_car(msrp=200_000, production_count=1_500)
        assert _estimate_floor(car_limited) > _estimate_floor(car_uncommon)

    def test_unknown_production_count_uses_base(self) -> None:
        car = _make_car(msrp=100_000, production_count=None, is_naturally_aspirated=False)
        floor = _estimate_floor(car)
        assert floor == 100_000 * BASE_FLOOR_FRACTION


# ─── _prepare_data ────────────────────────────────────────────────────────────

class TestPrepareData:
    def test_empty_sales(self) -> None:
        t, p = _prepare_data([], year_start=2019)
        assert len(t) == 0
        assert len(p) == 0

    def test_basic_conversion(self) -> None:
        # Sale in 2021-06, year_start=2019 → t = (2021-2019)*12 + 6 = 30
        sales = [_make_sale(sold_price=100_000, sold_year=2021, sold_month=6)]
        t, p = _prepare_data(sales, year_start=2019)
        assert len(t) == 1
        assert t[0] == 30.0
        assert p[0] == 100_000

    def test_older_sale_has_larger_t(self) -> None:
        sales = [
            _make_sale(sold_price=200_000, sold_year=2020, sold_month=1),
            _make_sale(sold_price=150_000, sold_year=2023, sold_month=1),
        ]
        t, p = _prepare_data(sales, year_start=2019)
        assert len(t) == 2
        # 2020-01 → t=13; 2023-01 → t=49
        assert t[t.argmin()] == 13.0  # older sale = smaller t
        assert t[t.argmax()] == 49.0

    def test_outlier_removal_via_mad(self) -> None:
        # 5 sales in the same month; one is a massive outlier
        # MAD-based detection (not std-based) correctly removes it
        sales = [
            _make_sale(sold_price=100_000, sold_year=2022, sold_month=6),
            _make_sale(sold_price=102_000, sold_year=2022, sold_month=6),
            _make_sale(sold_price=98_000, sold_year=2022, sold_month=6),
            _make_sale(sold_price=101_000, sold_year=2022, sold_month=6),
            _make_sale(sold_price=500_000, sold_year=2022, sold_month=6),  # outlier
        ]
        t, p = _prepare_data(sales, year_start=2019)
        assert 500_000 not in p

    def test_ignores_null_sold_price(self) -> None:
        sale = _make_sale(sold_price=100_000, sold_year=2022)
        sale.sold_price = None
        t, p = _prepare_data([sale], year_start=2019)
        assert len(t) == 0


# ─── _classify_buy_window ─────────────────────────────────────────────────────

class TestClassifyBuyWindow:
    """
    t convention: t = months since year_start; larger = older = more depreciated.
    current_t is the car's age right now.
    price_6m_ago = P(current_t - 6)  [car was 6 months younger, so higher price]
    """

    def _fit(
        self,
        *,
        p0: float = 80_000,
        lam: float = 0.03,
        floor: float = 50_000,
        residual_std: float = 5_000,
    ) -> FitResult:
        return FitResult(p0=p0, lam=lam, floor=floor, residual_std=residual_std)

    def test_at_floor_when_near_floor(self) -> None:
        # Very small p0 → current price ≈ floor + tiny amount
        fit = self._fit(p0=1_000, lam=0.5, floor=50_000)
        # current_t=48: P(48) = 1000*e^(-24) + 50000 ≈ 50000 ≤ 55000 → at_floor
        status, buy_date = _classify_buy_window(fit, 48.0, date(2024, 1, 1))
        assert status == "at_floor"
        assert buy_date == date(2024, 1, 1)

    def test_depreciating_fast_when_high_slope(self) -> None:
        # Large p0 with current_t=12: price = 150k*e^(-0.6)+50k ≈ 82k; floor*1.1=55k
        # slope is steep → depreciating_fast
        fit = self._fit(p0=150_000, lam=0.05, floor=50_000)
        # current_t=12: P(12) = 150k*e^(-0.6) + 50k ≈ 82.3k (well above 55k)
        # P(6) = 150k*e^(-0.3) + 50k ≈ 161k
        # six_month_drop = 161k - 82.3k = +78.7k (positive = prices fell → NOT appreciating)
        # first_deriv = -150k*0.05*e^(-0.6) ≈ -4116 ; threshold = 82.3k*0.005 = 411
        # |first_deriv| >> threshold → depreciating_fast
        status, _ = _classify_buy_window(fit, 12.0, date(2024, 1, 1))
        assert status == "depreciating_fast"

    def test_near_floor_when_slope_flat(self) -> None:
        # Tiny lam → nearly flat slope, price slightly above floor*1.1
        fit = FitResult(p0=6_000, lam=0.0001, floor=50_000, residual_std=1_000)
        # current_t=24: P(24) = 6000*e^(-0.0024) + 50000 ≈ 55985; floor*1.1=55000
        # 55985 > 55000 but first_deriv = -6000*0.0001*e^(-0.0024) ≈ -0.6
        # threshold = 55985*0.005 ≈ 280 → |first_deriv| < threshold → near_floor
        status, _ = _classify_buy_window(fit, 24.0, date(2024, 1, 1))
        assert status == "near_floor"

    def test_appreciating_when_price_rising(self) -> None:
        # Simulate a car whose price went UP over the last 6 months.
        # We can't do this with normal positive lam + p0. Instead, use a negative
        # p0 so P(t) increases with t (unusual but tests the branch).
        fit = FitResult(p0=-100_000, lam=0.05, floor=300_000, residual_std=5_000)
        # current_t=24: P(24) = -100k*e^(-1.2) + 300k = -30.1k + 300k = 269.9k
        # P(18) = -100k*e^(-0.9) + 300k = -40.7k + 300k = 259.3k
        # six_month_drop = 259.3k - 269.9k = -10.6k (negative → price went UP)
        # -10.6k < -(269.9k * 0.02 = 5.4k) → appreciating ✓
        status, _ = _classify_buy_window(fit, 24.0, date(2024, 1, 1))
        assert status == "appreciating"

    def test_depreciating_fast_projects_floor_date(self) -> None:
        fit = self._fit(p0=150_000, lam=0.05, floor=50_000)
        # current_t=40 → slope flattens ~26 months out (within PROJECTION_MONTHS=36)
        status, buy_date = _classify_buy_window(fit, 40.0, date(2024, 1, 1))
        assert status == "depreciating_fast"
        assert buy_date is not None
        assert buy_date > date(2024, 1, 1)


# ─── _build_summary ───────────────────────────────────────────────────────────

class TestBuildSummary:
    def _car(self) -> MagicMock:
        return _make_car(make="Ferrari", model="458", trim="Italia")

    def test_no_data_summary(self) -> None:
        summary = _build_summary(self._car(), "depreciating_fast", None, None)
        assert "Not enough" in summary

    def test_at_floor_summary(self) -> None:
        fit = FitResult(p0=50_000, lam=0.02, floor=120_000, residual_std=5_000)
        summary = _build_summary(self._car(), "at_floor", date(2024, 1, 1), fit)
        assert "optimal buy zone" in summary
        assert "120" in summary  # floor in $k

    def test_appreciating_summary(self) -> None:
        fit = FitResult(p0=50_000, lam=0.02, floor=120_000, residual_std=5_000)
        summary = _build_summary(self._car(), "appreciating", None, fit)
        assert "appreciating" in summary

    def test_depreciating_fast_with_date(self) -> None:
        fit = FitResult(p0=100_000, lam=0.03, floor=60_000, residual_std=5_000)
        buy_date = date(2025, 6, 1)
        summary = _build_summary(self._car(), "depreciating_fast", buy_date, fit)
        assert "depreciating" in summary.lower() or "still" in summary.lower()
        assert "June 2025" in summary

    def test_near_floor_summary(self) -> None:
        fit = FitResult(p0=10_000, lam=0.01, floor=80_000, residual_std=3_000)
        summary = _build_summary(self._car(), "near_floor", date(2024, 2, 1), fit)
        assert "approaching" in summary or "floor" in summary.lower()
