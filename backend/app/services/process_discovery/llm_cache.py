"""Disk cache of model replies for local development and evaluation runs (spec 11 §3.7).

Why: the same prompt is sent many times while a developer iterates or the evaluation re-runs its
personas, and each send costs Azure credit and seconds (`CLAUDE.md`: cache AI calls in local runs).
The cache holds replies that may quote expert text, so it is used only in stage `local` (the client
decides that) and the folder is git-ignored.
What: `LLMCache.key` hashes everything that shapes a reply (deployment, call type, messages,
response format, format version) into a SHA-256 key; `get` and `put` read and write
`<root>/<call_type>/<key[:2]>/<key>.json` with an atomic rename. A file that cannot be read is a
miss, logged by key only. Implements spec 11, AC-11.27 to AC-11.29 (with `llm.py`).
Must not: store errors or invalid output (the client calls `put` only with usable output), log any
text, or import anything from the engine (`call_type` is taken as a string; `CallType` is one).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.llm")

FORMAT_VERSION = 1
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_CALL_TYPE_RE = re.compile(r"^[A-Z][A-Z_]{0,31}$")


class LLMCache:
    """Model replies on disk, one JSON file per request key."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def key(
        deployment: str,
        call_type: str,
        messages: Sequence[Mapping[str, Any]],
        response_format: dict[str, Any] | str,
    ) -> str:
        """SHA-256 of the canonical JSON of everything that shapes the reply.

        `response_format` is the full strict schema for structured calls, `"json_object"` or `"text"`.
        """
        payload = {
            "v": FORMAT_VERSION,
            "deployment": deployment,
            "call_type": str(call_type),
            "messages": [dict(m) for m in messages],
            "response_format": response_format,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, call_type: str, key: str) -> Path:
        """Where one entry lives. Key and call type are checked, so no entry can name a path outside `root`."""
        if not _KEY_RE.match(key):
            raise ValueError("cache key must be a SHA-256 hex digest")
        if not _CALL_TYPE_RE.match(str(call_type)):
            raise ValueError("cache call type must be an upper-case identifier")
        return self.root / str(call_type) / key[:2] / f"{key}.json"

    def get(self, call_type: str, key: str) -> str | None:
        """The cached reply text, or `None` on a miss. A corrupt file is a miss, never an error."""
        path = self._path(call_type, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = data["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty or non-text entry")
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("llm_cache_corrupt", extra={"key": key})
            return None
        return text

    def put(self, call_type: str, key: str, text: str) -> None:
        """Store `text` under `key`: a temporary file in the same folder, then an atomic rename."""
        path = self._path(call_type, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"text": text, "created": datetime.now(UTC).isoformat()}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
