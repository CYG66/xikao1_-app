from __future__ import annotations

import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_ALLOWED_SUFFIXES = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".xml", ".srv", ".msg",
    ".py", ".cpp", ".hpp", ".h", ".c",
}
_EXCLUDED_PARTS = {
    ".git", ".pytest_cache", "__pycache__", "build", "install", "log",
    "node_modules", "outputs", "motion_output", "circle_output",
    "physical_square_output", "square_phase_output", "planned_results",
    "path_sg", "path_l", "wheelhouse", "tests", "test",
}
_SENSITIVE_NAME_PARTS = {"secret", "credential", "password", "private_key"}
_TOKEN_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_./-]*|[\u4e00-\u9fff]")
_SENSITIVE_LINE = re.compile(
    r"(?i)(api[_-]?key|password|passwd|secret|access[_-]?token)\s*[:=]"
)


@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    title: str
    line_start: int
    line_end: int
    text: str
    tokens: frozenset[str]


class ProjectKnowledgeRetriever:
    """Small dependency-free retriever for trusted project files."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] = ()
        self._chunks: list[KnowledgeChunk] = []
        self._last_scan_at = 0.0

    @staticmethod
    def _roots() -> list[tuple[str, Path]]:
        backend_root = Path(__file__).resolve().parents[1]
        configured = os.getenv("XLINE_KNOWLEDGE_ROOTS", "").strip()
        workspace = os.getenv("XLINE_WS_ROOT", os.getenv("XLINE_WS_DIR", "")).strip()
        candidates: list[tuple[str, Path]] = []
        if configured:
            for index, value in enumerate(configured.split(os.pathsep), start=1):
                if value.strip():
                    candidates.append((f"project_{index}", Path(value.strip())))
        else:
            candidates.append(("backend", backend_root))
            if workspace:
                candidates.append(("xline_ws3", Path(workspace)))
            elif os.name == "nt":
                candidates.append(("xline_ws3", Path(r"D:\xikao\xline_ws3")))
        unique: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for label, path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved).casefold()
            if resolved.exists() and key not in seen:
                unique.append((label, resolved))
                seen.add(key)
        return unique

    @staticmethod
    def _eligible(path: Path) -> bool:
        lowered_parts = {part.casefold() for part in path.parts}
        if lowered_parts.intersection(_EXCLUDED_PARTS):
            return False
        name = path.name.casefold()
        if name.startswith(".") or any(part in name for part in _SENSITIVE_NAME_PARTS):
            return False
        if name in {"cmakelists.txt", "package.xml"}:
            return True
        return path.suffix.casefold() in _ALLOWED_SUFFIXES

    def _files(self) -> list[tuple[str, Path, str]]:
        files: list[tuple[str, Path, str]] = []
        for label, root in self._roots():
            for current, directories, names in os.walk(root):
                directories[:] = sorted(
                    directory
                    for directory in directories
                    if directory.casefold() not in _EXCLUDED_PARTS
                    and not directory.startswith(".")
                )
                current_path = Path(current)
                for name in sorted(names):
                    path = current_path / name
                    if not self._eligible(path):
                        continue
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    if size <= 0 or size > 512 * 1024:
                        continue
                    relative = path.relative_to(root).as_posix()
                    files.append((label, path, f"{label}/{relative}"))
                    if len(files) >= 1200:
                        return files
        return files

    @staticmethod
    def _tokens(text: str) -> frozenset[str]:
        normalized = text.casefold()
        raw = _TOKEN_PATTERN.findall(normalized)
        chinese = [item for item in raw if len(item) == 1 and "\u4e00" <= item <= "\u9fff"]
        words = [item for item in raw if item not in chinese and len(item) > 1]
        bigrams = [chinese[index] + chinese[index + 1] for index in range(len(chinese) - 1)]
        return frozenset(words + bigrams)

    @staticmethod
    def _safe_lines(text: str) -> list[str]:
        return [
            "[敏感配置已隐藏]" if _SENSITIVE_LINE.search(line) else line.rstrip()
            for line in text.splitlines()
        ]

    @classmethod
    def _chunk_file(cls, source: str, path: Path) -> list[KnowledgeChunk]:
        try:
            lines = cls._safe_lines(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return []
        title = next(
            (line.lstrip("# ").strip() for line in lines[:30] if line.strip()),
            path.stem,
        )[:120]
        chunks: list[KnowledgeChunk] = []
        step, window = 24, 32
        for start in range(0, len(lines), step):
            selected = lines[start:start + window]
            text = "\n".join(selected).strip()
            if len(text) < 12:
                continue
            text = text[:2400]
            tokens = cls._tokens(f"{path.name} {title} {text}")
            if tokens:
                chunks.append(KnowledgeChunk(
                    source=source,
                    title=title,
                    line_start=start + 1,
                    line_end=min(len(lines), start + window),
                    text=text,
                    tokens=tokens,
                ))
        return chunks

    def _ensure_index(self) -> None:
        now = time.monotonic()
        if self._chunks and now - self._last_scan_at < 30.0:
            return
        files = self._files()
        signature_items: list[tuple[str, int, int]] = []
        for _, path, source in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            signature_items.append((source, stat.st_mtime_ns, stat.st_size))
        signature = tuple(signature_items)
        if signature == self._signature:
            self._last_scan_at = now
            return
        with self._lock:
            if signature == self._signature:
                return
            chunks: list[KnowledgeChunk] = []
            for _, path, source in files:
                chunks.extend(self._chunk_file(source, path))
            self._chunks = chunks
            self._signature = signature
            self._last_scan_at = now

    def search(self, query: str, limit: int = 4) -> dict[str, Any]:
        self._ensure_index()
        query_tokens = self._tokens(query)
        maximum = max(1, min(limit, 8))
        if not query_tokens:
            return {"query": query, "matches": [], "indexed_chunks": len(self._chunks)}
        scored: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            overlap = query_tokens.intersection(chunk.tokens)
            if not overlap:
                continue
            coverage = len(overlap) / len(query_tokens)
            density = len(overlap) / math.sqrt(max(1, len(chunk.tokens)))
            phrase_bonus = 0.4 if query.casefold() in chunk.text.casefold() else 0.0
            score = coverage * 3.0 + density + phrase_bonus
            if score >= 0.45:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].source, item[1].line_start))
        matches: list[dict[str, Any]] = []
        used_sources: set[str] = set()
        for score, chunk in scored:
            if chunk.source in used_sources and len(matches) >= 2:
                continue
            citation = f"K{len(matches) + 1}"
            matches.append({
                "id": citation,
                "title": chunk.title,
                "source": chunk.source,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "score": round(score, 4),
                "excerpt": chunk.text[:1200],
            })
            used_sources.add(chunk.source)
            if len(matches) >= maximum:
                break
        return {
            "query": query,
            "matches": matches,
            "indexed_chunks": len(self._chunks),
        }


project_knowledge = ProjectKnowledgeRetriever()
