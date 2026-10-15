"""Historical floor sheets (every trade, with buyer/seller broker numbers)
from merolagani.com/Floorsheet.aspx.

NEPSE's own API only serves the latest session's floor sheet, and only
publishes broker ids after the close -- so any day the post-close sweep
missed (every day before 2026-10-15) can't be repaired from NEPSE.
merolagani keeps the full floor sheet per date, verified 2026-10-15 back to
2020-03-16 (2018-01 returned nothing), with totals matching NEPSE exactly
for recent days (e.g. 2026-10-15: 38,861 = 38,861).

It is an ASP.NET WebForms page: search by date with a postback
(txtFloorsheetDateFilter, MM/DD/YYYY), then page through 500-row pages by
posting the pager's hidden hdnCurrentPage (any page number can be jumped
to). Each postback must carry the previous response's __VIEWSTATE, so one
FloorSheetHistory instance reads one date's pages sequentially.

Columns: #, Transact. No. (= NEPSE contract id), Symbol, Buyer (broker
no.), Seller (broker no.), Quantity, Rate, Amount. There is no trade time
and no broker name.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import requests

_URL = "https://merolagani.com/Floorsheet.aspx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": _URL,
}
_PREFIX = "ctl00$ContentPlaceHolder1$"

_HIDDEN_RE = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"')
_SUMMARY_RE = re.compile(r"Showing\s+[\d,]+\s*-\s*[\d,]+\s+of\s+([\d,]+)\s+records\.\s*\[Total pages:\s*([\d,]+)\]")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>|\s+")


def _num(text: str) -> float | None:
    text = text.replace(",", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _int(text: str) -> int | None:
    value = _num(text)
    return int(value) if value is not None else None


class FloorSheetHistory:
    """Reads one past date's floor sheet page by page."""

    def __init__(self, timeout: int = 60) -> None:
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._html = ""
        self._date_text = ""

    def _post(self, fields: dict[str, str]) -> None:
        form = dict(_HIDDEN_RE.findall(self._html))
        form.update(fields)
        resp = self._session.post(_URL, data=form, timeout=self._timeout)
        resp.raise_for_status()
        self._html = resp.text

    def _parse(self) -> tuple[int, int, list[dict[str, Any]]]:
        m = _SUMMARY_RE.search(self._html)
        if not m:
            return 0, 0, []
        total_records = int(m.group(1).replace(",", ""))
        total_pages = int(m.group(2).replace(",", ""))

        start = self._html.find("<table")
        end = self._html.find("</table>", start)
        rows = []
        for row_html in _ROW_RE.findall(self._html[start:end]):
            cells = [_TAG_RE.sub(" ", c).strip() for c in _CELL_RE.findall(row_html)]
            if len(cells) != 8:
                continue
            _, contract_id, symbol, buyer, seller, qty, rate, amount = cells
            if not contract_id.isdigit() or not symbol:
                continue
            rows.append(
                {
                    "contract_id": int(contract_id),
                    "symbol": symbol,
                    "buyer_member_id": _int(buyer),
                    "seller_member_id": _int(seller),
                    "contract_quantity": _int(qty),
                    "contract_rate": _num(rate),
                    "contract_amount": _num(amount),
                }
            )
        return total_records, total_pages, rows

    def open(self, day: date) -> tuple[int, int, list[dict[str, Any]]]:
        """Search `day`; returns (total_records, total_pages, page-1 rows).
        (0, 0, []) when merolagani has no floor sheet for that date."""
        resp = self._session.get(_URL, timeout=self._timeout)
        resp.raise_for_status()
        self._html = resp.text
        self._date_text = day.strftime("%m/%d/%Y")
        self._post(
            {
                "__EVENTTARGET": f"{_PREFIX}lbtnSearchFloorsheet",
                "__EVENTARGUMENT": "",
                f"{_PREFIX}txtFloorsheetDateFilter": self._date_text,
                f"{_PREFIX}ASCompanyFilter$txtAutoSuggest": "",
                f"{_PREFIX}txtBuyerBrokerCodeFilter": "",
                f"{_PREFIX}txtSellerBrokerCodeFilter": "",
            }
        )
        return self._parse()

    def page(self, number: int) -> tuple[int, int, list[dict[str, Any]]]:
        """1-based page of the date passed to open()."""
        self._post(
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                f"{_PREFIX}txtFloorsheetDateFilter": self._date_text,
                f"{_PREFIX}PagerControl1$hdnCurrentPage": str(number),
                f"{_PREFIX}PagerControl1$btnPaging": "",
            }
        )
        return self._parse()
