"""Raw page artifact storage."""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.settings import settings


@dataclass(frozen=True)
class StoredArtifact:
    artifact_uri: str
    content_sha256: str
    size_bytes: int
    content_type: str


class ArtifactStore(Protocol):
    async def save(
        self,
        *,
        source: str,
        content: bytes,
        content_type: str,
        fetched_at: datetime | None = None,
    ) -> StoredArtifact:
        """Persist raw content and return its addressable artifact metadata."""

    async def load(self, artifact_uri: str) -> bytes:
        """Load raw uncompressed content by artifact URI."""

    async def exists(self, artifact_uri: str) -> bool:
        """Return whether an artifact URI exists."""


class LocalArtifactStore:
    """Gzip artifacts on disk behind opaque local:// URIs."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    async def save(
        self,
        *,
        source: str,
        content: bytes,
        content_type: str,
        fetched_at: datetime | None = None,
    ) -> StoredArtifact:
        fetched_at = fetched_at or datetime.now(UTC)
        digest = hashlib.sha256(content).hexdigest()
        extension = _extension_for_content_type(content_type)
        relative_path = Path(source) / fetched_at.strftime("%Y/%m/%d") / f"{digest}.{extension}.gz"
        path = self.root_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with gzip.open(path, "wb") as file:
                file.write(content)
        return StoredArtifact(
            artifact_uri=f"local://{relative_path.as_posix()}",
            content_sha256=digest,
            size_bytes=len(content),
            content_type=content_type,
        )

    async def load(self, artifact_uri: str) -> bytes:
        path = self._path_for_uri(artifact_uri)
        with gzip.open(path, "rb") as file:
            return file.read()

    async def exists(self, artifact_uri: str) -> bool:
        return self._path_for_uri(artifact_uri).exists()

    def _path_for_uri(self, artifact_uri: str) -> Path:
        if not artifact_uri.startswith("local://"):
            raise ValueError(f"Unsupported artifact URI for local store: {artifact_uri}")
        return self.root_dir / artifact_uri.removeprefix("local://")


def get_artifact_store() -> ArtifactStore:
    if settings.raw_page_artifact_backend != "local":
        raise ValueError(
            f"Unsupported raw artifact backend: {settings.raw_page_artifact_backend}"
        )
    return LocalArtifactStore(settings.raw_page_storage_dir)


def _extension_for_content_type(content_type: str) -> str:
    lowered = content_type.lower()
    if "json" in lowered:
        return "json"
    if "html" in lowered:
        return "html"
    return "bin"
