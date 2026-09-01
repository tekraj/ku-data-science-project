"""Parse Nepali Bikram Sambat calendar text into a Gregorian datetime.
Needed for portals (annapurnapost.com, setopati.com) whose article pages
carry no machine-readable published-date at all -- confirmed directly
during backfill research: no <time datetime>, no article:published_time
meta tag, no JSON-LD datePublished, only BS text in the rendered page.
Two distinct field orderings are seen in the wild:
  - "०८ भदौ २०८३, सोमबार"                    (day month year[, weekday])
  - "प्रकाशित मिति: बिहीबार, असार १८, २०८३"   (weekday, month day, year)

Conversion itself is delegated to the `nepali-datetime` package rather than
hand-rolled, since BS/AD conversion tables are easy to get subtly wrong.
"""
from __future__ import annotations

import re
from datetime import datetime

import nepali_datetime

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# BS month name -> month number. Includes the common alternate spellings
# seen across Nepali news portals.
_NEPALI_MONTHS: dict[str, int] = {
    "बैशाख": 1, "बैसाख": 1, "वैशाख": 1,
    "जेठ": 2, "जेष्ठ": 2,
    "असार": 3, "आषाढ": 3, "आषाढ़": 3,
    "श्रावण": 4, "सावन": 4, "साउन": 4,
    "भदौ": 5, "भाद्र": 5, "भदौं": 5,
    "असोज": 6, "आश्विन": 6, "आश्विन्": 6,
    "कार्तिक": 7, "कार्तीक": 7,
    "मंसिर": 8, "मार्ग": 8, "मार्गशीर्ष": 8,
    "पौष": 9, "पुष": 9,
    "माघ": 10,
    "फागुन": 11, "फाल्गुन": 11,
    "चैत": 12, "चैत्र": 12,
}

# "day month year" -- e.g. "०८ भदौ २०८३, सोमबार" (annapurnapost.com).
_BS_DATE_RE_DAY_MONTH_YEAR = re.compile(r"([०-९]+)\s+([^\s,०-९]+)\s+([०-९]+)")

# "month day, year" -- e.g. "असार १८, २०८३" (setopati.com, after its
# "प्रकाशित मिति: <weekday>," prefix).
_BS_DATE_RE_MONTH_DAY_YEAR = re.compile(r"([^\s,०-९]+)\s+([०-९]+),\s*([०-९]+)")


def _bs_ymd_to_ad(day: int, month: int, year: int) -> datetime | None:
    try:
        bs_date = nepali_datetime.date(year, month, day)
        ad_date = bs_date.to_datetime_date()
    except Exception:
        return None
    return datetime(ad_date.year, ad_date.month, ad_date.day)


def parse_bs_date_text(text: str) -> datetime | None:
    """Parse Nepali BS calendar text in either recognized field ordering
    (see module docstring) into a Gregorian datetime (midnight). Returns
    None if the text doesn't match either shape or names an unrecognized
    month."""
    if not text:
        return None

    stripped = text.strip()

    match = _BS_DATE_RE_DAY_MONTH_YEAR.search(stripped)
    if match:
        day_str, month_str, year_str = match.groups()
        month = _NEPALI_MONTHS.get(month_str.strip())
        if month is not None:
            result = _bs_ymd_to_ad(
                int(day_str.translate(_DEVANAGARI_DIGITS)),
                month,
                int(year_str.translate(_DEVANAGARI_DIGITS)),
            )
            if result is not None:
                return result

    match = _BS_DATE_RE_MONTH_DAY_YEAR.search(stripped)
    if match:
        month_str, day_str, year_str = match.groups()
        month = _NEPALI_MONTHS.get(month_str.strip())
        if month is not None:
            result = _bs_ymd_to_ad(
                int(day_str.translate(_DEVANAGARI_DIGITS)),
                month,
                int(year_str.translate(_DEVANAGARI_DIGITS)),
            )
            if result is not None:
                return result

    return None
