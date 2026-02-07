"""robots.txt compliance checker for REGDOCS scraping.

Uses urllib.robotparser to respect site crawling rules.
If robots.txt is missing or unreadable, scraping is allowed (standard practice).
"""

from __future__ import annotations

import logging
import urllib.robotparser

logger = logging.getLogger(__name__)


def check_robots_allowed(
    base_url: str,
    target_path: str,
    user_agent: str,
) -> bool:
    """Check whether robots.txt permits fetching the given path.

    Args:
        base_url: The site root (e.g., "https://apps.cer-rec.gc.ca/REGDOCS").
        target_path: The path to check (e.g., "/Search/RecentFilings").
        user_agent: The User-Agent string to check against.

    Returns:
        True if scraping is allowed, False if disallowed by robots.txt.
    """
    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"{base_url.rstrip('/')}/robots.txt"
    rp.set_url(robots_url)

    try:
        rp.read()
    except Exception:
        logger.warning(
            "Could not read robots.txt at %s -- assuming scraping is allowed",
            robots_url,
        )
        return True

    # Check for crawl-delay directive and log it
    crawl_delay = rp.crawl_delay(user_agent)
    if crawl_delay is not None:
        logger.info(
            "robots.txt specifies crawl-delay of %s seconds for %s",
            crawl_delay,
            user_agent,
        )

    full_url = f"{base_url.rstrip('/')}{target_path}"
    allowed = rp.can_fetch(user_agent, full_url)

    if not allowed:
        logger.warning(
            "robots.txt disallows fetching %s for user-agent %s",
            full_url,
            user_agent,
        )

    return allowed
