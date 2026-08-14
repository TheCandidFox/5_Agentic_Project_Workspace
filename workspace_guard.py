from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Iterable


class AccessMode(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class WorkspaceViolation(PermissionError):
    """Raised when a requested path is outside the granted workspace policy."""


@dataclass(frozen=True)
class AuthorizedPath:
    path: Path
    relative_path: str
    access: AccessMode


class WorkspaceGuard:
    """Application-layer path authorization for a single candidate workspace.

    This guard resolves existing symlinks/junctions before granting access and
    rejects lexical traversal even when it would normalize back into the root.
    It is a policy boundary for orchestrator code, not an operating-system
    sandbox for an already-started subprocess.
    """

    DEFAULT_PROTECTED_NAMES = frozenset({".env", "secrets.env", ".git", ".venv"})
    WINDOWS_RESERVED_NAMES = frozenset(
        {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{number}" for number in range(1, 10)),
            *(f"lpt{number}" for number in range(1, 10)),
        }
    )

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        protected_names: Iterable[str] | None = None,
        immutable_paths: Iterable[str | Path] = (),
    ) -> None:
        root = Path(workspace_root).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"workspace root does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"workspace root is not a directory: {root}")

        self.root = root.resolve(strict=True)
        names = protected_names if protected_names is not None else self.DEFAULT_PROTECTED_NAMES
        self.protected_names = frozenset(name.casefold() for name in names)
        self._immutable = tuple(
            self._resolve_candidate(path, reject_traversal=True)
            for path in immutable_paths
        )

    @staticmethod
    def _has_parent_traversal(path: str | Path) -> bool:
        return ".." in PurePath(str(path).replace("\\", "/")).parts

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(str(left)) == os.path.normcase(str(right))

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path_key = os.path.normcase(os.path.abspath(path))
            root_key = os.path.normcase(os.path.abspath(root))
            return os.path.commonpath((path_key, root_key)) == root_key
        except ValueError:
            return False

    @classmethod
    def _validate_path_components(cls, requested: str | Path) -> None:
        raw = Path(requested)
        for part in raw.parts:
            if part == raw.anchor:
                continue
            if ":" in part:
                raise WorkspaceViolation(f"alternate data streams are not allowed: {requested}")
            if part != part.rstrip(" ."):
                raise WorkspaceViolation(f"unsafe trailing character in path: {requested}")
            device_name = part.split(".", 1)[0].casefold()
            if device_name in cls.WINDOWS_RESERVED_NAMES:
                raise WorkspaceViolation(f"reserved device name in path: {requested}")

    def _resolve_candidate(
        self,
        requested: str | Path,
        *,
        reject_traversal: bool,
    ) -> Path:
        if not str(requested).strip():
            raise WorkspaceViolation("path must not be empty")
        if reject_traversal and self._has_parent_traversal(requested):
            raise WorkspaceViolation(f"parent traversal is not allowed: {requested}")
        self._validate_path_components(requested)

        raw = Path(requested).expanduser()
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.resolve(strict=False)
        if not self._is_within(resolved, self.root):
            raise WorkspaceViolation(f"path is outside workspace: {requested}")
        return resolved

    def _relative_parts(self, path: Path) -> tuple[str, ...]:
        relative = path.relative_to(self.root)
        return tuple(part.rstrip(" .").casefold() for part in relative.parts)

    def _check_protected(self, path: Path) -> None:
        parts = self._relative_parts(path)
        protected = self.protected_names.intersection(parts)
        if protected:
            name = sorted(protected)[0]
            raise WorkspaceViolation(f"protected workspace path: {name}")
        for part in parts:
            if part.startswith(".env.") and part != ".env.example":
                raise WorkspaceViolation(f"protected workspace path: {part}")

    def _check_immutable(self, path: Path, access: AccessMode) -> None:
        if access == AccessMode.READ:
            return
        for immutable in self._immutable:
            if self._same_path(path, immutable) or self._is_within(path, immutable):
                relative = immutable.relative_to(self.root).as_posix()
                raise WorkspaceViolation(f"immutable workspace path: {relative}")

    def authorize(
        self,
        requested: str | Path,
        access: AccessMode | str,
        *,
        must_exist: bool | None = None,
        expect_directory: bool | None = None,
    ) -> AuthorizedPath:
        mode = AccessMode(access)
        path = self._resolve_candidate(requested, reject_traversal=True)
        self._check_protected(path)
        self._check_immutable(path, mode)

        required = mode in {AccessMode.READ, AccessMode.EXECUTE} if must_exist is None else must_exist
        if required and not path.exists():
            raise FileNotFoundError(f"authorized path does not exist: {requested}")

        if path.exists() and expect_directory is True and not path.is_dir():
            raise NotADirectoryError(f"expected a directory: {requested}")
        if path.exists() and expect_directory is False and not path.is_file():
            raise IsADirectoryError(f"expected a file: {requested}")

        relative = path.relative_to(self.root).as_posix() or "."
        return AuthorizedPath(path=path, relative_path=relative, access=mode)

    def authorize_read(
        self,
        requested: str | Path,
        *,
        expect_directory: bool | None = None,
    ) -> AuthorizedPath:
        return self.authorize(
            requested,
            AccessMode.READ,
            must_exist=True,
            expect_directory=expect_directory,
        )

    def authorize_write(
        self,
        requested: str | Path,
        *,
        expect_directory: bool | None = None,
    ) -> AuthorizedPath:
        return self.authorize(
            requested,
            AccessMode.WRITE,
            must_exist=False,
            expect_directory=expect_directory,
        )

    def authorize_directory(
        self,
        requested: str | Path = ".",
        *,
        access: AccessMode | str = AccessMode.READ,
    ) -> AuthorizedPath:
        return self.authorize(
            requested,
            access,
            must_exist=True,
            expect_directory=True,
        )
