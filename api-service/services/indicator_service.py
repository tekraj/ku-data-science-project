"""Pure-Python technical indicator math for NEPSE index series.

Design contract
----------------
Every function here operates on ``values: list[float | None]`` -- a daily
close series ordered oldest to newest, aligned 1:1 with a parallel list of
dates that the *caller* manages separately (this module never sees dates).

None-until-enough-history: an indicator's rolling window at position ``i``
needs a certain number of trailing data points to be well-defined (e.g. a
20-period SMA needs 20 trailing closes). Wherever that requirement is not
met -- not enough prior points yet, or the input is degenerate (empty,
shorter than the period, all None) -- the function returns ``None`` at that
position rather than fabricating a value from a short/partial window or
raising an exception. This is a real, expected data constraint for indices
with short scrape history (see nepse_service.get_indicators), and the API
surfaces it honestly via a `days_available` count rather than silently
truncating or lying about the window size used.

Forward-fill rationale: a `None` in the raw series represents a calendar
day where no scrape happened to land (a gap in scraping), not a day the
market was inactive. Feeding those gaps directly into rolling-window math
would shrink the effective window unpredictably and produce artifacts (a
sudden jump the moment a None drops out of a trailing window) that have
nothing to do with the index itself. `forward_fill` treats a missing scrape
as "value unchanged since last known", which is the standard, conservative
way to carry a last-observation forward for smoothing math, and keeps every
window the intended fixed size. Leading Nones (no observation yet at all)
are left as None since there is nothing to carry forward. All indicator
functions here consume the forward-filled series internally; whether the
*caller* also wants to display forward-filled or raw values (e.g. a price
line that should show real gaps) is a decision left to the caller -- see
NepseIndexService.get_indicators, which keeps the original (non-filled)
closes for display and only forward-fills the copy fed to indicator math.

Every function tolerates, without raising:
  * an all-None input list
  * an input shorter than `period`
  * a `period` exactly equal to the input length
and returns an all-None list of the same length as `values` in those cases.
"""

from __future__ import annotations

import math

__all__ = [
    "forward_fill",
    "compute_sma",
    "compute_ema",
    "compute_macd",
    "compute_rsi",
    "compute_bollinger_bands",
]


def forward_fill(values: list[float | None]) -> list[float | None]:
    """Fill gaps with the most recent prior non-None value.

    Leading None values (before the first real observation) are left as
    None -- there is nothing yet to carry forward. See module docstring for
    the rationale (a missing scrape day is treated as "unchanged since last
    known value", not a genuine gap in the index's activity).
    """
    result: list[float | None] = []
    last_seen: float | None = None
    for v in values:
        if v is not None:
            last_seen = v
        result.append(last_seen)
    return result


def compute_sma(values: list[float | None], period: int) -> list[float | None]:
    """Simple moving average over `period` trailing values (post forward-fill).

    Returns None until `period` prior (non-None) points are available at
    that position. Handles empty input, input shorter than `period`, and
    period == len(values) without raising.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n == 0 or period <= 0:
        return result

    filled = forward_fill(values)

    window_sum = 0.0
    window_count = 0  # number of non-None values currently in the trailing window
    for i in range(n):
        v = filled[i]
        window_sum += v if v is not None else 0.0
        window_count += 1 if v is not None else 0

        if i >= period:
            drop = filled[i - period]
            window_sum -= drop if drop is not None else 0.0
            window_count -= 1 if drop is not None else 0

        if i >= period - 1 and window_count == period:
            result[i] = window_sum / period

    return result


def compute_ema(values: list[float | None], period: int) -> list[float | None]:
    """Exponential moving average, alpha = 2 / (period + 1).

    Seeded with a simple average of the first `period` (post forward-fill)
    values, then the standard EMA recurrence for subsequent points. Returns
    None until the seed window is available.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n == 0 or period <= 0 or period > n:
        return result

    filled = forward_fill(values)

    # Find the seed window: the first `period` values starting once we have
    # a full run of non-None entries (forward_fill only leaves leading Nones
    # as None, so once the first non-None appears the rest are non-None).
    first_valid = None
    for i, v in enumerate(filled):
        if v is not None:
            first_valid = i
            break
    if first_valid is None:
        return result  # all-None input

    seed_end = first_valid + period - 1  # index of last value in seed window
    if seed_end >= n:
        return result  # not enough points after the first valid value

    seed_values = filled[first_valid : first_valid + period]
    if any(v is None for v in seed_values):
        return result

    alpha = 2.0 / (period + 1)
    ema = sum(seed_values) / period
    result[seed_end] = ema

    for i in range(seed_end + 1, n):
        v = filled[i]
        if v is None:
            result[i] = None
            continue
        ema = (v - ema) * alpha + ema
        result[i] = ema

    return result


def compute_macd(
    values: list[float | None],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """MACD line (ema_fast - ema_slow), its signal line, and histogram.

    macd_line[i] is None wherever either the fast or slow EMA is None at i.
    signal is the EMA of macd_line over `signal` periods, seeded from the
    first `signal` non-None macd_line points. histogram = macd - signal.
    """
    n = len(values)
    empty = {"macd": [None] * n, "signal": [None] * n, "histogram": [None] * n}
    if n == 0:
        return empty

    ema_fast = compute_ema(values, fast)
    ema_slow = compute_ema(values, slow)

    macd_line: list[float | None] = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # EMA of macd_line, skipping leading Nones for the seed.
    signal_line = compute_ema(macd_line, signal)

    histogram: list[float | None] = [None] * n
    for i in range(n):
        if macd_line[i] is not None and signal_line[i] is not None:
            histogram[i] = macd_line[i] - signal_line[i]

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def compute_rsi(values: list[float | None], period: int = 14) -> list[float | None]:
    """RSI using Wilder's smoothing (the conventional RSI definition).

    Computes period-over-period diffs on the forward-filled series, seeds
    average gain/loss as a simple average of the first `period` diffs, then
    applies Wilder's recurrence: avg = (prev_avg * (period - 1) + current) / period.
    RSI = 100 - 100 / (1 + avg_gain / avg_loss); avg_loss == 0 => RSI = 100.
    Returns None until enough prior points exist.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n == 0 or period <= 0 or period >= n:
        return result

    filled = forward_fill(values)

    # Find the first index with a real value; diffs are only meaningful
    # from the second valid observation onward.
    first_valid = None
    for i, v in enumerate(filled):
        if v is not None:
            first_valid = i
            break
    if first_valid is None:
        return result

    diffs: list[float | None] = [None] * n
    for i in range(first_valid + 1, n):
        prev = filled[i - 1]
        cur = filled[i]
        if prev is not None and cur is not None:
            diffs[i] = cur - prev

    # Seed window: first `period` diffs starting right after first_valid.
    seed_start = first_valid + 1
    seed_end = seed_start + period - 1  # inclusive index of last diff in seed
    if seed_end >= n:
        return result

    seed_diffs = diffs[seed_start : seed_start + period]
    if any(d is None for d in seed_diffs):
        return result

    gains = [d if d > 0 else 0.0 for d in seed_diffs]
    losses = [-d if d < 0 else 0.0 for d in seed_diffs]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    result[seed_end] = _rsi_from_avgs(avg_gain, avg_loss)

    for i in range(seed_end + 1, n):
        d = diffs[i]
        if d is None:
            result[i] = None
            continue
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[i] = _rsi_from_avgs(avg_gain, avg_loss)

    return result


def compute_bollinger_bands(
    values: list[float | None],
    period: int = 20,
    num_std: float = 2.0,
) -> dict:
    """Bollinger Bands: middle = SMA(period), upper/lower = middle +/- num_std * stddev.

    Uses the *population* standard deviation (divide by `period`, not
    `period - 1`) of the trailing window, matching the same fixed-size
    window the middle-band SMA already uses. None until enough prior
    points exist for a full window.
    """
    n = len(values)
    empty = {"upper": [None] * n, "middle": [None] * n, "lower": [None] * n}
    if n == 0 or period <= 0 or period > n:
        return empty

    filled = forward_fill(values)
    middle = compute_sma(values, period)

    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n

    for i in range(n):
        if middle[i] is None:
            continue
        window = filled[i - period + 1 : i + 1]
        if any(w is None for w in window):
            continue
        mean = middle[i]
        variance = sum((w - mean) ** 2 for w in window) / period
        std = math.sqrt(variance)
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std

    return {"upper": upper, "middle": middle, "lower": lower}
