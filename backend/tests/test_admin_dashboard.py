"""Tests for the ingestion-only admin dashboard."""

from __future__ import annotations

import pytest

from app.api import admin


@pytest.mark.asyncio
async def test_admin_status_does_not_require_secret() -> None:
    status = await admin.get_status()

    assert isinstance(status.is_running, bool)
    assert not hasattr(status, "effective_secret_hint")


@pytest.mark.asyncio
async def test_admin_dashboard_is_ingestion_only() -> None:
    response = await admin.admin_dashboard()
    html = response.body.decode()

    assert "secret-input" not in html
    assert "auth-gate" not in html
    assert "doLogin" not in html
    assert "Admin secret" not in html
    assert "Depreciation" not in html
    assert "Watchlist" not in html
    assert "Prediction" not in html
    assert "Cars.com" not in html
    assert "Auction Lots" in html
    assert "Source Health" in html
    assert "Request Logs" in html
    assert "<th>Target</th>" in html
    assert "<th>Total</th>" in html
    assert "<th>Skipped</th>" in html
    assert "Anomalies" in html
    assert "triggerScrape" in html
