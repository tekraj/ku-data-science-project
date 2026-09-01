"""Canonical union of the three separate _SYMBOL_TO_INDEX_NAME dicts found in the
old monolith (nepse-news-scraper), for use by NEW code only:

- scraper/nepse_scraper.py           (uppercase symbol keys)
- scraper/historical_nepse_loader.py (uppercase symbol keys, superset of the above)
- scraper/merolagani_scraper.py      (lowercase/spaced display-name keys)

No key/value conflicts were found across the three sources: nepse_scraper.py's
mappings are an exact subset of historical_nepse_loader.py's, and
merolagani_scraper.py uses an entirely separate lowercase key namespace that does
not collide (case-insensitively) with the other two. Per the build instructions,
had any conflict existed, historical_nepse_loader.py's value would take
precedence with a comment noting the conflict -- none was needed here.
"""

SYMBOL_TO_INDEX_NAME: dict[str, str] = {
    # From historical_nepse_loader.py / nepse_scraper.py (uppercase symbol keys).
    "NEPSE": "NEPSE",
    "BANKING": "Banking SubIndex",
    "DEVBANK": "Development Bank Index",
    "FINANCE": "Finance Index",
    "HOTELS": "Hotels And Tourism Index",
    "HYDROPOWER": "HydroPower Index",
    "INVESTMENT": "Investment Index",
    "LIFEINSU": "Life Insurance",
    "MANUFACTURE": "Manufacturing And Processing",
    "MICROFINANCE": "Microfinance Index",
    "NONLIFEINSU": "Non Life Insurance",
    "TRADING": "Trading Index",
    "OTHERS": "Others Index",
    # From merolagani_scraper.py (lowercase/spaced display-name keys).
    "banking": "Banking SubIndex",
    "development bank": "Development Bank Index",
    "finance": "Finance Index",
    "hydropower": "HydroPower Index",
    "microfinance": "Microfinance Index",
    "life insurance": "Life Insurance",
    "non-life insurance": "Non Life Insurance",
    "non life insurance": "Non Life Insurance",
    "trading": "Trading Index",
    "hotels and tourism": "Hotels And Tourism Index",
    "investment": "Investment Index",
    "manufacturing and processing": "Manufacturing And Processing",
    "sensitive": "Sensitive Index",
    "sen. float": "Sensitive Float Index",
    "sen float": "Sensitive Float Index",
    "float": "Float Index",
    "nepse": "NEPSE",
}
