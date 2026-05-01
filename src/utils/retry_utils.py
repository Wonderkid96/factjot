from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential


def io_retry():
    return retry(
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
