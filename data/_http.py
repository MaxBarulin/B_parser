"""Tiny HTTP wrapper with retry/backoff for exchange REST."""
from __future__ import annotations

import time

import requests
from tqdm import tqdm


def get_json(url: str, params: dict | None = None, timeout: int = 30, retries: int = 4):
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(2 ** attempt)
    assert last_err is not None
    raise last_err


def get_bytes(url: str, timeout: int = 300, retries: int = 4, desc: str | None = None) -> bytes:
    """Streamed download with per-file byte progress bar."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with requests.get(url, timeout=timeout, stream=True) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0) or 0)
                chunks: list[bytes] = []
                bar = tqdm(
                    total=total or None,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=desc or "download",
                    leave=False,
                )
                try:
                    for chunk in r.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            chunks.append(chunk)
                            bar.update(len(chunk))
                finally:
                    bar.close()
                return b"".join(chunks)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == retries - 1:
                break
            time.sleep(2 ** attempt)
    assert last_err is not None
    raise last_err


_UNITS_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}


def interval_to_ms(interval: str) -> int:
    """Convert e.g. '5m', '1h', '1d' to milliseconds."""
    return int(interval[:-1]) * _UNITS_MS[interval[-1]]
