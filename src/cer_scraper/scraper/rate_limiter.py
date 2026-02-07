"""Centralized rate limiter for REGDOCS requests.

Produces randomized delays between configurable min and max seconds
to avoid predictable request patterns that could trigger rate limiting.
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)


def wait_between_requests(
    min_seconds: float = 1.0,
    max_seconds: float = 3.0,
) -> float:
    """Sleep for a random duration between min_seconds and max_seconds.

    Args:
        min_seconds: Minimum delay in seconds.
        max_seconds: Maximum delay in seconds.

    Returns:
        The actual delay applied (useful for testing).
    """
    delay = random.uniform(min_seconds, max_seconds)
    logger.debug("Rate limit: waiting %.1fs", delay)
    time.sleep(delay)
    return delay
