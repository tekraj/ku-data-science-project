"""Auth-token derivation for the official nepalstock.com.np JSON API.

nepalstock.com (and its underlying API host nepalstock.com.np) is a Single
Page Application whose real data lives behind /api/nots/... endpoints that
require an `Authorization: Salter <token>` header. That token is NOT a
static secret -- confirmed directly: a plain requests.get to
/api/nots/market/today-price with no such header returns HTTP 401
"WARNING: UNAUTHORIZED ACCESS". The token is instead derived per-request
via a small WebAssembly module the SPA loads and executes client-side.

This module ports the token-derivation mechanism from the MIT-licensed
open-source `nepse-scraper` package (PyPI nepse-scraper==0.1.7, by
polymorphisma, github.com/polymorphisma/nepse_scraper) rather than adding
it as a pip dependency, since we only need this one piece of it (the rest
of that package is a thin requests wrapper we don't need, and vendoring
keeps the token/payload math visible and auditable in this repo instead of
opaque inside a third-party wheel). nepse.wasm below is copied byte-for-byte
from that package (it is in fact WAT -- WebAssembly Text format, despite the
.wasm extension -- wasmtime's Module.from_file auto-detects and parses that
directly, no separate compile step needed).

Flow, verified against the nepse-scraper package source (see Scraper.py's
TokenParser/PayloadParser/Nepse classes):
  1. GET /api/authenticate/prove -> JSON with accessToken, refreshToken,
     and salt1..salt5 (ints).
  2. Feed the 5 salts through 5 WASM-exported functions (cdx, rdx, bdx,
     ndx, mdx), called twice each with the salts permuted a specific way,
     to get 5 character-removal indices into accessToken (and, via a
     second permutation, into refreshToken -- refresh_token is unused here
     since we only ever need a fresh access token per call).
  3. Slice accessToken at those 5 indices (removing 5 characters total) to
     get the REAL bearer token. Send it as `Authorization: Salter <token>`.
  4. Most POST-style calls additionally require a numeric `id` in the JSON
     body, derived from a dummy-data lookup table + day-of-month arithmetic
     + more salt math (see build_payload_id below) -- separate from the
     header token.

NEPSE's TLS cert chain is incomplete for this host (verify=False required
-- confirmed directly: curl reports "unable to get local issuer
certificate" even though the handshake itself succeeds). This is a known,
accepted issue specific to nepalstock.com.np, not something to silently
carry over to requests against other sites in this codebase.
"""
from __future__ import annotations

import os
from datetime import datetime
from importlib import resources
from typing import Any

import requests
from wasmtime import Instance, Module, Store

ROOT_URL = "https://www.nepalstock.com.np"

_HEADERS = {
    "Host": "www.nepalstock.com.np",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nepalstock.com.np/",
}

# Same dummy-data lookup table as the upstream nepse-scraper package --
# this is NOT tunable/configurable data, it is a fixed constant baked into
# NEPSE's own client-side JS that the payload-id math has to reproduce
# exactly to be accepted server-side.
_DUMMY_DATA = [
    147, 117, 239, 143, 157, 312, 161, 612, 512, 804, 411, 527, 170, 511,
    421, 667, 764, 621, 301, 106, 133, 793, 411, 511, 312, 423, 344, 346,
    653, 758, 342, 222, 236, 811, 711, 611, 122, 447, 128, 199, 183, 135,
    489, 703, 800, 745, 152, 863, 134, 211, 142, 564, 375, 793, 212, 153,
    138, 153, 648, 611, 151, 649, 318, 143, 117, 756, 119, 141, 717, 113,
    112, 146, 162, 660, 693, 261, 362, 354, 251, 641, 157, 178, 631, 192,
    734, 445, 192, 883, 187, 122, 591, 731, 852, 384, 565, 596, 451, 772,
    624, 691,
]


class _TokenParser:
    """Loads nepse.wasm once and exposes the 5 index-deriving functions."""

    def __init__(self) -> None:
        wasm_path = resources.files(__package__).joinpath("nepse.wasm")
        with resources.as_file(wasm_path) as path:
            store = Store()
            module = Module.from_file(store.engine, str(path))
            instance = Instance(store, module, [])

        self._store = store
        exports = instance.exports(store)
        self._cdx = exports["cdx"]
        self._rdx = exports["rdx"]
        self._bdx = exports["bdx"]
        self._ndx = exports["ndx"]
        self._mdx = exports["mdx"]

    def parse_access_token(self, token_response: dict[str, Any]) -> str:
        s1, s2, s3, s4, s5 = (
            token_response["salt1"],
            token_response["salt2"],
            token_response["salt3"],
            token_response["salt4"],
            token_response["salt5"],
        )
        store = self._store
        n = self._cdx(store, s1, s2, s3, s4, s5)
        l = self._rdx(store, s1, s2, s4, s3, s5)
        o = self._bdx(store, s1, s2, s4, s3, s5)
        p = self._ndx(store, s1, s2, s4, s3, s5)
        q = self._mdx(store, s1, s2, s4, s3, s5)

        access_token = token_response["accessToken"]
        return (
            access_token[0:n]
            + access_token[n + 1 : l]
            + access_token[l + 1 : o]
            + access_token[o + 1 : p]
            + access_token[p + 1 : q]
            + access_token[q + 1 :]
        )


# The WASM module load (parsing the .wat text + instantiating it) is cheap
# but non-zero; do it once per process rather than once per activity call.
_token_parser: _TokenParser | None = None


def _get_token_parser() -> _TokenParser:
    global _token_parser
    if _token_parser is None:
        _token_parser = _TokenParser()
    return _token_parser


def fetch_auth_context(timeout: int) -> dict[str, Any]:
    """GET /api/authenticate/prove and return the parsed access token
    alongside the raw salts (still needed by build_payload_id below).

    Called fresh per activity invocation rather than cached across ticks:
    at this codebase's 1-minute NEPSE market-data schedule interval, the
    extra GET /api/authenticate/prove round-trip per tick is a small,
    acceptable cost, and NEPSE does not document a token TTL we could
    safely cache against -- re-deriving fresh each time trades a bit of
    redundant latency for correctness certainty.
    """
    resp = requests.get(
        ROOT_URL + "/api/authenticate/prove",
        headers=_HEADERS,
        timeout=timeout,
        verify=False,  # NEPSE's cert chain is incomplete -- see module docstring.
    )
    resp.raise_for_status()
    token_response = resp.json()

    for i in range(1, 6):
        token_response[f"salt{i}"] = int(token_response[f"salt{i}"])

    access_token = _get_token_parser().parse_access_token(token_response)
    return {"access_token": access_token, "salts": token_response}


def build_payload_id(auth_context: dict[str, Any], which: str | None = None) -> int:
    """Reproduces PayloadParser.return_payload from the upstream package:
    calls the market-open endpoint (any authenticated GET works as the
    seed call -- upstream always uses market-open for this) to get a
    small `id` value, then combines it with _DUMMY_DATA and
    day-of-month arithmetic to compute the numeric payload id some
    POST-style nepalstock.com.np endpoints require in the request body.
    Kept faithful to the upstream derivation rather than simplified, since
    this is exactly the kind of obfuscation logic where "simplifying" risks
    silently producing a value the server rejects.
    """
    salts = auth_context["salts"]
    access_token = auth_context["access_token"]

    headers = {"Authorization": f"Salter {access_token}", **_HEADERS}
    resp = requests.get(
        ROOT_URL + "/api/nots/nepse-data/market-open",
        headers=headers,
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    given_id = resp.json()["id"]

    today = datetime.now().day
    payload_id = _DUMMY_DATA[given_id] + given_id + 2 * today

    if which == "stock-live":
        return payload_id

    if which == "sector-live":
        index_value = 3 if payload_id % 10 < 5 else 1
    else:
        index_value = 1 if payload_id % 10 < 5 else 3

    payload_id = (
        payload_id
        + salts[f"salt{index_value + 1}"] * today
        - salts[f"salt{index_value}"]
    )
    return payload_id


def auth_headers(auth_context: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Salter {auth_context['access_token']}", **_HEADERS}
