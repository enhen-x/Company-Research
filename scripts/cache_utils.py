#!/usr/bin/env python3
"""Shared disk cache utilities.

Houses ``ScreenerCache`` — a Parquet-based disk cache with TTL — used by both
the screener (Tier 1/2) and the Tushare collector's heavy-endpoint TTL cache.
"""

from __future__ import annotations

import hashlib
import os
import time

import pandas as pd


class ScreenerCache:
    """Parquet-based disk cache with TTL."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{safe_key}.parquet")

    def _meta_path(self, key: str) -> str:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{safe_key}.meta")

    def get(self, key: str, ttl_seconds: int) -> pd.DataFrame | None:
        """Return cached DataFrame if within TTL, else None."""
        path = self._path(key)
        meta_path = self._meta_path(key)
        if not os.path.exists(path) or not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path) as f:
                ts = float(f.read().strip().split("\n")[0])
            if time.time() - ts > ttl_seconds:
                return None
            return pd.read_parquet(path)
        except Exception:
            return None

    def put(self, key: str, df: pd.DataFrame) -> None:
        """Store DataFrame to cache."""
        path = self._path(key)
        meta_path = self._meta_path(key)
        try:
            df.to_parquet(path, index=False)
            with open(meta_path, "w") as f:
                f.write(f"{time.time()}\n{key}")
        except Exception:
            pass  # cache write failure is non-fatal

    def invalidate(self, key: str) -> None:
        """Remove a cache entry."""
        for p in [self._path(key), self._meta_path(key)]:
            if os.path.exists(p):
                os.remove(p)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove cache entries whose original key starts with prefix."""
        if not os.path.isdir(self.cache_dir):
            return
        for f in os.listdir(self.cache_dir):
            if not f.endswith(".meta"):
                continue
            fp = os.path.join(self.cache_dir, f)
            try:
                with open(fp) as fh:
                    lines = fh.read().strip().split("\n")
                original_key = lines[1] if len(lines) > 1 else ""
                if original_key.startswith(prefix):
                    os.remove(fp)
                    parquet = fp.replace(".meta", ".parquet")
                    if os.path.exists(parquet):
                        os.remove(parquet)
            except Exception:
                pass

    def clear(self) -> None:
        """Remove all cache entries."""
        if os.path.isdir(self.cache_dir):
            for f in os.listdir(self.cache_dir):
                fp = os.path.join(self.cache_dir, f)
                if os.path.isfile(fp):
                    os.remove(fp)
