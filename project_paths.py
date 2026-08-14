from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_absolute_on_any_platform(value: str) -> bool:
    return (
        Path(value).is_absolute()
        or bool(_WINDOWS_ABSOLUTE.match(value))
        or value.startswith("\\\\")
        or value.startswith("//")
    )


def _legacy_tail(value: str, anchor: str) -> str | None:
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    matches = [index for index, part in enumerate(parts) if part.casefold() == anchor.casefold()]
    if not matches:
        return None
    return PurePosixPath(*parts[matches[-1] :]).as_posix()


def portable_project_path(
    value: str | Path,
    project_root: str | Path,
    *,
    legacy_anchor: str | None = None,
) -> str:
    """Return a safe, POSIX-style path relative to ``project_root``.

    ``legacy_anchor`` supports migration of an old absolute path when its stable
    project-relative suffix is known. For example, an artifact formerly stored
    as ``C:\\old-machine\\project\\outputs\\result.md`` becomes
    ``outputs/result.md``.
    """

    raw = str(value).strip()
    if not raw:
        raise ValueError("path must not be empty")

    root = Path(project_root).resolve()
    candidate = Path(raw).expanduser()

    if candidate.is_absolute():
        try:
            return candidate.resolve(strict=False).relative_to(root).as_posix()
        except ValueError:
            if legacy_anchor:
                tail = _legacy_tail(raw, legacy_anchor)
                if tail:
                    return tail
            raise ValueError(f"absolute path is outside project root: {raw}")

    if _looks_absolute_on_any_platform(raw):
        if legacy_anchor:
            tail = _legacy_tail(raw, legacy_anchor)
            if tail:
                return tail
        raise ValueError(f"absolute path is outside project root: {raw}")

    portable = PurePosixPath(raw.replace("\\", "/"))
    if portable.is_absolute() or ".." in portable.parts:
        raise ValueError(f"path escapes project root: {raw}")
    return portable.as_posix()


def resolve_project_path(
    value: str | Path,
    project_root: str | Path,
    *,
    legacy_anchor: str | None = None,
) -> Path:
    portable = portable_project_path(
        value,
        project_root,
        legacy_anchor=legacy_anchor,
    )
    return Path(project_root).resolve().joinpath(*PurePosixPath(portable).parts)


def resolve_config_path(value: str | Path, project_root: str | Path) -> Path:
    """Resolve a user-configured path, defaulting relative values to the project."""

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (Path(project_root) / candidate).resolve(strict=False)
