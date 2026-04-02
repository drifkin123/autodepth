"""Tests for the car catalog API routes.

All database interactions are mocked — no real DB connections.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


# ─── Fixtures ───────────────────────────────────────────────────────────────

class _FakeCar:
    """Plain object to avoid MagicMock interfering with pydantic from_attributes."""

    def __init__(self, **kwargs: object) -> None:
        defaults = {
            "id": uuid.uuid4(),
            "make": "Porsche",
            "model": "911",
            "trim": "GT3 RS",
            "year_start": 2018,
            "year_end": 2023,
            "production_count": 1500,
            "engine": "4.0L NA Flat-6",
            "is_naturally_aspirated": True,
            "msrp_original": 188000,
            "notes": None,
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        for key, val in defaults.items():
            setattr(self, key, val)


def _make_car(**overrides: object) -> _FakeCar:
    return _FakeCar(**overrides)


class _FakeSale:
    def __init__(self, car_id: uuid.UUID, **kwargs: object) -> None:
        defaults = {
            "id": uuid.uuid4(),
            "car_id": car_id,
            "source": "bring_a_trailer",
            "source_url": "https://bringatrailer.com/listing/example/",
            "sale_type": "auction",
            "year": 2020,
            "mileage": 5000,
            "color": "White",
            "asking_price": 195000,
            "sold_price": 190000,
            "is_sold": True,
            "listed_at": datetime(2025, 3, 1, tzinfo=timezone.utc),
            "sold_at": datetime(2025, 3, 5, tzinfo=timezone.utc),
            "condition_notes": None,
        }
        defaults.update(kwargs)
        for key, val in defaults.items():
            setattr(self, key, val)


def _make_sale(car_id: uuid.UUID, **overrides: object) -> _FakeSale:
    return _FakeSale(car_id, **overrides)


# ─── Tests ──────────────────────────────────────────────────────────────────

class TestListCars:
    def test_returns_list_of_cars(self) -> None:
        car = _make_car()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [car]
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/cars")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["make"] == "Porsche"
            assert data[0]["yearStart"] == 2018
        finally:
            app.dependency_overrides.clear()

    def test_returns_empty_when_no_cars(self) -> None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/cars")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()


class TestGetCar:
    def test_returns_car_by_id(self) -> None:
        car = _make_car()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{car.id}")
            assert resp.status_code == 200
            assert resp.json()["trim"] == "GT3 RS"
        finally:
            app.dependency_overrides.clear()

    def test_returns_404_for_unknown_id(self) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{uuid.uuid4()}")
            assert resp.status_code == 404
            assert "not found" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


class TestGetCarSales:
    def test_returns_paginated_sales(self) -> None:
        car = _make_car()
        sale = _make_sale(car.id)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        sales_result = MagicMock()
        sales_result.scalars.return_value.all.return_value = [sale]

        mock_db.execute = AsyncMock(side_effect=[count_result, sales_result])

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{car.id}/sales?page=1&page_size=10")
            assert resp.status_code == 200
            body = resp.json()
            assert body["sales"]["total"] == 1
            assert body["sales"]["page"] == 1
            assert len(body["sales"]["items"]) == 1
            assert body["car"]["make"] == "Porsche"
        finally:
            app.dependency_overrides.clear()

    def test_sales_404_for_unknown_car(self) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{uuid.uuid4()}/sales")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestGetPriceHistory:
    def test_returns_price_history(self) -> None:
        car = _make_car()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        row = MagicMock()
        row.yr = 2025.0
        row.mo = 3.0
        row.avg_sold = 185000.0
        row.avg_asking = 190000.0
        row.sold_count = 5
        row.listing_count = 8

        mock_result = MagicMock()
        mock_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{car.id}/price-history")
            assert resp.status_code == 200
            body = resp.json()
            assert body["car"]["make"] == "Porsche"
            assert len(body["priceHistory"]) == 1
            assert body["priceHistory"][0]["date"] == "2025-03"
            assert body["priceHistory"][0]["soldCount"] == 5
        finally:
            app.dependency_overrides.clear()

    def test_price_history_404_for_unknown_car(self) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{uuid.uuid4()}/price-history")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()
