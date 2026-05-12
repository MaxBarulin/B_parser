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


def get_bytes(
    url: str,
    connect_timeout: float = 30.0,
    read_timeout: float = 90.0,
    retries: int = 6,
    desc: str | None = None,
) -> bytes:
    """Streamed download with byte progress and HTTP Range resume on retry.

    `read_timeout` is the per-chunk read timeout: if no bytes arrive within
    this window the connection is killed and we resume from where we left
    off (S3/CloudFront support Range requests, so we don't restart from 0).
    """
    buf = bytearray()
    last_err: Exception | None = None
    bar: tqdm | None = None

    for attempt in range(retries):
        headers = {"Range": f"bytes={len(buf)}-"} if buf else {}
        try:
            with requests.get(
                url,
                timeout=(connect_timeout, read_timeout),
                stream=True,
                headers=headers,
            ) as r:
                # If we asked for a range but server replied 200, it ignored
                # our Range header — restart from scratch with that response.
                if buf and r.status_code == 200:
                    buf.clear()
                    if bar is not None:
                        bar.close()
                        bar = None
                r.raise_for_status()

                total: int | None = None
                if r.status_code == 206:
                    cr = r.headers.get("content-range", "")
                    if "/" in cr:
                        try:
                            total = int(cr.split("/")[-1])
                        except ValueError:
                            total = None
                else:
                    cl = r.headers.get("content-length")
                    total = int(cl) if cl else None

                if bar is None:
                    bar = tqdm(
                        total=total,
                        initial=len(buf),
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=desc or "download",
                        leave=False,
                    )

                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        buf.extend(chunk)
                        bar.update(len(chunk))

                if total is not None and len(buf) < total:
                    raise OSError(f"truncated stream: {len(buf)}/{total}")

                if bar is not None:
                    bar.close()
                return bytes(buf)

        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 16))
                continue
            break

    if bar is not None:
        bar.close()
    assert last_err is not None
    raise last_err


_UNITS_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}


def interval_to_ms(interval: str) -> int:
    """Convert e.g. '5m', '1h', '1d' to milliseconds."""
    return int(interval[:-1]) * _UNITS_MS[interval[-1]]
