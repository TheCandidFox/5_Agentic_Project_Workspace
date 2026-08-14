from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    kind: str
    symbol: str
    preview: str


def lexical_search(root: str | Path, query: str, limit: int = 20) -> list[Hit]:
    root = Path(root)
    rx = re.compile(re.escape(query), re.I)
    hits: list[Hit] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"
        }:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                hits.append(
                    Hit(str(path), i, "lexical", query, line.strip()[:240])
                )
                if len(hits) >= limit:
                    return hits
    return hits


def python_symbol_index(root: str | Path) -> dict[str, list[Hit]]:
    root = Path(root)
    index: dict[str, list[Hit]] = {}
    for path in root.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
            lines = source.splitlines()
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = (
                    "class" if isinstance(node, ast.ClassDef)
                    else "async_function" if isinstance(node, ast.AsyncFunctionDef)
                    else "function"
                )
                hit = Hit(
                    path=str(path),
                    line=node.lineno,
                    kind=kind,
                    symbol=node.name,
                    preview=lines[node.lineno - 1].strip()[:240],
                )
                index.setdefault(node.name, []).append(hit)
    return index


def find_symbol(root: str | Path, symbol: str) -> list[Hit]:
    return python_symbol_index(root).get(symbol, [])
