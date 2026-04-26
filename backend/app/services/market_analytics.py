"""Analytics helpers for market chart endpoints."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import mean, median

from app.models.auction_lot import AuctionLot


def integer_average(values: list[int]) -> int | None:
    if not values:
        return None
    return round(mean(values))


def integer_median(values: list[int]) -> int | None:
    if not values:
        return None
    return round(median(values))


def percentage_change(current: int | None, previous: int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round(((current - previous) / previous) * 100, 1)


def movement_for_window(lots: list[AuctionLot], days: int) -> float | None:
    dated = [lot for lot in lots if lot.ended_at and lot.sold_price is not None]
    if not dated:
        return None
    latest = max(lot.ended_at for lot in dated)
    current_start = latest - timedelta(days=days)
    previous_start = latest - timedelta(days=days * 2)
    current = [lot.sold_price for lot in dated if lot.ended_at >= current_start and lot.sold_price]
    previous = [
        lot.sold_price
        for lot in dated
        if previous_start <= lot.ended_at < current_start and lot.sold_price
    ]
    return percentage_change(integer_median(current), integer_median(previous))


def monthly_buckets(lots: list[AuctionLot]) -> list[dict]:
    buckets: dict[date, list[int]] = defaultdict(list)
    for lot in lots:
        if lot.ended_at and lot.sold_price is not None:
            buckets[date(lot.ended_at.year, lot.ended_at.month, 1)].append(lot.sold_price)
    return [
        {
            "month": month,
            "average_price": round(mean(values)),
            "median_price": round(median(values)),
            "minimum_price": min(values),
            "maximum_price": max(values),
            "count": len(values),
        }
        for month, values in sorted(buckets.items())
    ]


def linear_trend(points: list[tuple[float, float]]) -> dict | None:
    if not points:
        return None
    if len(points) == 1:
        x, y = points[0]
        return {"slope": 0.0, "intercept": y, "points": [{"x": x, "y": y}]}
    x_mean = mean(point[0] for point in points)
    y_mean = mean(point[1] for point in points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    slope = 0.0 if math.isclose(denominator, 0) else (
        sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    )
    intercept = y_mean - slope * x_mean
    x_values = [point[0] for point in points]
    trend_points = [
        {"x": min(x_values), "y": round(slope * min(x_values) + intercept, 2)},
        {"x": max(x_values), "y": round(slope * max(x_values) + intercept, 2)},
    ]
    return {"slope": round(slope, 4), "intercept": round(intercept, 2), "points": trend_points}


def days_since_epoch(value: datetime) -> float:
    return (value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)).days
