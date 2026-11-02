"""Portable file fingerprints shared by inventories and render input snapshots."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FileFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
            raise ValueError("File paths must be relative POSIX paths inside the dataset root")
        return value


def json_sha256(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fingerprint_file(root: Path, path: Path) -> FileFingerprint:
    root, resolved = root.resolve(), path.resolve()
    relative = resolved.relative_to(root)
    digest = hashlib.sha256()
    with resolved.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return FileFingerprint(path=relative.as_posix(), sha256=digest.hexdigest(), size_bytes=resolved.stat().st_size)
