"""Tests for the admin dashboard access behavior."""

from __future__ import annotations

import pytest

from app.api import admin


@pytest.mark.asyncio
async def test_admin_status_does_not_require_secret() -> None:
    status = await admin.get_status()

    assert isinstance(status.is_running, bool)
    assert status.effective_secret_hint == ""


@pytest.mark.asyncio
async def test_admin_dashboard_has_no_password_gate() -> None:
    response = await admin.admin_dashboard()
    html = response.body.decode()

    assert "secret-input" not in html
    assert "auth-gate" not in html
    assert "doLogin" not in html
    assert "Admin secret" not in html
    assert "initDashboard" in html
