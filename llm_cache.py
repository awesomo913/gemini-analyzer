"""On-disk cache for LLM results — each conversation is processed at most once.

Stored under the user config dir (AppData/Local/GeminiAnalyzer/llm_cache on Windows),
which is OUTSIDE the repo, so cached conversation-derived results are never committed.

Keyed by (namespace, model, key) so re-categorizing with a different model doesn't
collide with cached insights, and switching models re-computes instead of serving stale.
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from config_manager import get_config_dir

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    root = get_config_dir() / "llm_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


class LLMCache:
    """Namespaced key/value cache backed by small JSON files."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    def _path(self, namespace: str, model: str, key: str) -> Path:
        safe_ns = "".join(c for c in namespace if c.isalnum() or c in ("_", "-")) or "default"
        digest = hashlib.sha256(f"{model}::{key}".encode("utf-8")).hexdigest()[:32]
        ns_dir = _cache_root() / safe_ns
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{digest}.json"

    def get(self, namespace: str, model: str, key: str) -> Optional[Any]:
        """`key` should be a stable identifier (e.g. a conversation id), NOT raw
        prompt text — it is hashed for the filename, and only the hash is logged."""
        if not self.enabled:
            return None
        path = self._path(namespace, model, key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.hits += 1
            return payload.get("value")
        except (json.JSONDecodeError, OSError) as e:
            # Corrupt cache entry — treat as miss, don't crash the caller.
            # Log the filename hash, never the key (which could carry text).
            logger.warning("Cache read failed for %s/%s: %s", namespace, path.stem, e)
            self.misses += 1
            return None

    def set(self, namespace: str, model: str, key: str, value: Any) -> bool:
        """`key` should be a stable identifier (e.g. a conversation id), NOT raw
        prompt text — it is hashed for the filename, and only the hash is logged."""
        if not self.enabled:
            return False
        path = self._path(namespace, model, key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"model": model, "value": value}, f, default=str)
            return True
        except OSError as e:
            logger.warning("Cache write failed for %s/%s: %s", namespace, path.stem, e)
            return False

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }

    def clear(self, namespace: Optional[str] = None) -> int:
        """Delete cached files. Returns count removed. Cache-only — never touches user data."""
        root = _cache_root()
        target = (root / namespace) if namespace else root
        if not target.exists():
            return 0
        count = 0
        for f in target.rglob("*.json"):
            try:
                f.unlink()
                count += 1
            except OSError as e:
                logger.warning("Cache clear: could not delete %s: %s", f.name, e)
        return count
