"""Tests for the watchlist API routes.

All database interactions and auth are mocked — no real DB or Clerk.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from app.db import get_db
from app.main import app

FAKE_USER = "user_test_123"


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_car(**overrides: object) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "make": "Ferrari",
        "model": "488",
        "trim": "Pista",
        "year_start": 2018,
        "year_end": 2020,
        "production_count": 3500,
        "engine": "3.9L Twin-Turbo V8",
        "is_naturally_aspirated": False,
        "msrp_original": 350000,
        "notes": None,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    car = MagicMock()
    for key, val in defaults.items():
        setattr(car, key, val)
    return car


def _make_watchlist_item(car_id: uuid.UUID, **overrides: object) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": FAKE_USER,
        "car_id": car_id,
        "target_price": 280000,
        "notes": "Wait for floor",
        "added_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    item = MagicMock()
    for key, val in defaults.items():
        setattr(item, key, val)
    return item


def _override_auth() -> str:
    return FAKE_USER


# ─── Tests ──────────────────────────────────────────────────────────────────

class TestGetWatchlist:
    @patch("app.api.watchlist.compute_depreciation_result")
    def test_returns_enriched_items(self, mock_dep: MagicMock) -> None:
        car = _make_car()
        item = _make_watchlist_item(car.id)

        dep_result = MagicMock()
        dep_result.fit = None
        dep_result.predictions = []
        dep_result.buy_window_status = "Near floor"
        mock_dep.return_value = dep_result

        mock_db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [item]
        mock_db.execute = AsyncMock(return_value=exec_result)
        mock_db.get = AsyncMock(return_value=car)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.get("/api/watchlist")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["car"]["make"] == "Ferrari"
            assert data[0]["buyWindowStatus"] is None  # fit is None
        finally:
            app.dependency_overrides.clear()

    def test_returns_empty_for_no_items(self) -> None:
        mock_db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=exec_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.get("/api/watchlist")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.clear()


class TestAddToWatchlist:
    def test_creates_item(self) -> None:
        car = _make_car()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        # No existing item
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=no_result)
        mock_db.commit = AsyncMock()

        async def _fake_refresh(item: object) -> None:
            # Simulate DB setting added_at on insert
            if not hasattr(item, "added_at") or item.added_at is None:
                item.added_at = datetime(2025, 6, 1, tzinfo=timezone.utc)

        mock_db.refresh = AsyncMock(side_effect=_fake_refresh)
        mock_db.add = MagicMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/watchlist",
                json={"car_id": str(car.id), "target_price": 250000},
            )
            assert resp.status_code == 201
            mock_db.add.assert_called_once()
            mock_db.commit.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()

    def test_returns_409_on_duplicate(self) -> None:
        car = _make_car()
        existing_item = _make_watchlist_item(car.id)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=car)

        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = existing_item
        mock_db.execute = AsyncMock(return_value=dup_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/watchlist",
                json={"car_id": str(car.id)},
            )
            assert resp.status_code == 409
            assert "already" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    def test_returns_404_for_unknown_car(self) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/watchlist",
                json={"car_id": str(uuid.uuid4())},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestRemoveFromWatchlist:
    def test_deletes_own_item(self) -> None:
        car = _make_car()
        item = _make_watchlist_item(car.id)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=item)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.delete(f"/api/watchlist/{item.id}")
            assert resp.status_code == 204
            mock_db.delete.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()

    def test_returns_404_for_wrong_user(self) -> None:
        car = _make_car()
        item = _make_watchlist_item(car.id, user_id="someone_else")

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=item)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.delete(f"/api/watchlist/{item.id}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_returns_404_for_missing_item(self) -> None:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_current_user_id] = _override_auth
        try:
            client = TestClient(app)
            resp = client.delete(f"/api/watchlist/{uuid.uuid4()}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()
