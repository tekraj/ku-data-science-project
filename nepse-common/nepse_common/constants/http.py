"""Shared HTTP headers, copied verbatim from the old monolith's scraper modules.

scraper/nepse_scraper.py and scraper/merolagani_scraper.py each define their own
_HEADERS dict with a different "Accept" value, but both use an identical
"User-Agent" string -- that shared entry is what's captured here."""

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
