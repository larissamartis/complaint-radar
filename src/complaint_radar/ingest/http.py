"""Resumable-safe HTTP download shared by archive and snapshot ingestion."""

import logging
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)


def download(url: str, target: Path, session=None, retries: int = 3, backoff: float = 5.0) -> Path:
    """Download `url` to `target` via a `.part` file; skip if `target` already has the remote size."""
    session = session or requests.Session()
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            head = session.head(url, timeout=60, allow_redirects=True)
            head.raise_for_status()
            expected = int(head.headers["Content-Length"])
            if target.exists() and target.stat().st_size == expected:
                log.info("skip %s (complete)", target.name)
                return target
            with session.get(url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with part.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            if part.stat().st_size != expected:
                raise OSError(f"size mismatch for {target.name}: {part.stat().st_size} != {expected}")
            part.replace(target)
            return target
        except (OSError, KeyError, ValueError, requests.RequestException) as exc:
            part.unlink(missing_ok=True)
            if attempt == retries:
                raise
            log.warning("download %s failed (%s); retry %d/%d", target.name, exc, attempt, retries)
            time.sleep(backoff * attempt)
    raise AssertionError("unreachable")
