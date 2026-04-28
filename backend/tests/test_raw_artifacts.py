"""Tests for raw artifact storage."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from app.services.artifacts import LocalArtifactStore


@pytest.mark.asyncio
async def test_local_artifact_store_saves_gzip_content_by_hash(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    content = b"<html><body>BaT archive</body></html>"
    fetched_at = datetime(2026, 4, 28, 12, 30, tzinfo=UTC)

    stored = await store.save(
        source="bring_a_trailer",
        content=content,
        content_type="text/html",
        fetched_at=fetched_at,
    )

    assert stored.artifact_uri.startswith("local://bring_a_trailer/2026/04/28/")
    assert stored.artifact_uri.endswith(".html.gz")
    assert stored.content_sha256 == hashlib.sha256(content).hexdigest()
    assert stored.size_bytes == len(content)
    assert await store.exists(stored.artifact_uri)
    assert await store.load(stored.artifact_uri) == content

    duplicate = await store.save(
        source="bring_a_trailer",
        content=content,
        content_type="text/html",
        fetched_at=fetched_at,
    )
    assert duplicate.artifact_uri == stored.artifact_uri
