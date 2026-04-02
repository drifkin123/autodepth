"""Tests for the prediction and compare API routes.

Mocks the depreciation service and compare summary — no real DB.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


class _FakeCar:
    def __init__(self, **kwargs: object) -> None:
        defaults = {
            "id": uuid.uuid4(), "make": "Porsche", "model": "911",
            "trim": "GT3", "year_start": 2018, "year_end": 2023,
            "production_count": 4000, "engine": "4.0L NA Flat-6",
            "is_naturally_aspirated": True, "msrp_original": 162000,
            "notes": None, "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        defaults.update(kwargs)
        for key, val in defaults.items():
            setattr(self, key, val)


class _FakePrediction:
    def __init__(self, car_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.car_id = car_id
        self.model_version = "v1"
        self.predicted_for = date(2026, 6, 1)
        self.predicted_price = 140000
        self.confidence_low = 125000
        self.confidence_high = 155000
        self.generated_at = datetime(2025, 4, 1, tzinfo=timezone.utc)


class _FakeDepResult:
    def __init__(self, car_id: uuid.UUID) -> None:
        self.predictions = [_FakePrediction(car_id)]
        self.buy_window_status = "near_floor"
        self.buy_window_date = date(2026, 9, 1)
        self.summary = "The 911 GT3 is approaching its price floor."
        self.fit = MagicMock()


class TestGetPrediction:
    @patch("app.api.predictions.compute_depreciation_result")
    def test_returns_prediction_for_car(self, mock_dep: MagicMock) -> None:
        car = _FakeCar()
        mock_dep.return_value = _FakeDepResult(car.id)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{car.id}/prediction")
            assert resp.status_code == 200
            body = resp.json()
            assert body["buyWindowStatus"] == "near_floor"
            assert body["summary"] == "The 911 GT3 is approaching its price floor."
            assert len(body["predictions"]) == 1
            assert body["predictions"][0]["predictedPrice"] == 140000
        finally:
            app.dependency_overrides.clear()

    @patch("app.api.predictions.compute_depreciation_result")
    def test_returns_404_for_unknown_car(self, mock_dep: MagicMock) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/cars/{uuid.uuid4()}/prediction")
            assert resp.status_code == 404
            mock_dep.assert_not_called()
        finally:
            app.dependency_overrides.clear()


class TestCompareCars:
    @patch("app.services.compare_summary.generate_compare_summary")
    @patch("app.api.predictions.compute_depreciation_result")
    def test_compare_with_valid_ids(
        self, mock_dep: MagicMock, mock_summary: MagicMock
    ) -> None:
        car_a = _FakeCar(make="Porsche", model="911", trim="GT3")
        car_b = _FakeCar(make="Ferrari", model="488", trim="Pista")

        mock_dep.side_effect = [
            _FakeDepResult(car_a.id),
            _FakeDepResult(car_b.id),
        ]
        mock_summary.return_value = "The GT3 is the better buy."

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=[car_a, car_b])

        row = MagicMock()
        row.yr = 2025.0
        row.mo = 1.0
        row.avg_sold = 150000.0
        row.avg_asking = 160000.0
        row.sold_count = 3
        row.listing_count = 5

        price_result = MagicMock()
        price_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=price_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            ids = f"{car_a.id},{car_b.id}"
            resp = client.get(f"/api/compare?ids={ids}")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["cars"]) == 2
            assert body["aiSummary"] == "The GT3 is the better buy."
        finally:
            app.dependency_overrides.clear()

    def test_compare_rejects_single_id(self) -> None:
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get(f"/api/compare?ids={uuid.uuid4()}")
            assert resp.status_code == 422
            assert "2 and 4" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_compare_rejects_invalid_uuid(self) -> None:
        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/compare?ids=not-a-uuid,also-bad")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @patch("app.services.compare_summary.generate_compare_summary")
    @patch("app.api.predictions.compute_depreciation_result")
    def test_compare_404_when_car_missing(
        self, mock_dep: MagicMock, mock_summary: MagicMock
    ) -> None:
        car_a = _FakeCar()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(side_effect=[car_a, None])

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            client = TestClient(app)
            ids = f"{car_a.id},{uuid.uuid4()}"
            resp = client.get(f"/api/compare?ids={ids}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()
