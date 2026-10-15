"""Every NEPSE index this codebase tracks, with its identifier on each source.

- official_id: nepalstock.com.np's numeric index id (/api/nots/nepse-index,
  /api/nots, /api/nots/index/history/{id}).
- name: canonical name stored in nepse_index.index_name /
  nepse_index_daily.index_name / nepse_intraday_tick.symbol. These match the
  names already present in nepse_index (they are nepalstock's own names,
  except "NEPSE Index" which this codebase has always stored as "NEPSE").
- merolagani_symbol: symbol accepted by merolagani.com's
  TechnicalChartHandler (its Indices.aspx dropdown labels, case-insensitive)
  -- verified 2026-10-15 to return daily history for all 17.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NepseIndexSpec:
    official_id: int
    name: str
    merolagani_symbol: str


INDEX_REGISTRY: tuple[NepseIndexSpec, ...] = (
    NepseIndexSpec(58, "NEPSE", "NEPSE"),
    NepseIndexSpec(57, "Sensitive Index", "Sensitive"),
    NepseIndexSpec(62, "Float Index", "Float"),
    NepseIndexSpec(63, "Sensitive Float Index", "Sen. Float"),
    NepseIndexSpec(51, "Banking SubIndex", "Banking"),
    NepseIndexSpec(52, "Hotels And Tourism Index", "Hotels And Tourism"),
    NepseIndexSpec(53, "Others Index", "Others"),
    NepseIndexSpec(54, "HydroPower Index", "Hydropower"),
    NepseIndexSpec(55, "Development Bank Index", "Development Bank"),
    NepseIndexSpec(56, "Manufacturing And Processing", "Manu.and Pro."),
    NepseIndexSpec(59, "Non Life Insurance", "Non-Life Insurance"),
    NepseIndexSpec(60, "Finance Index", "Finance"),
    NepseIndexSpec(61, "Trading Index", "Trading"),
    NepseIndexSpec(64, "Microfinance Index", "Microfinance"),
    NepseIndexSpec(65, "Life Insurance", "Life Insurance"),
    NepseIndexSpec(66, "Mutual Fund", "Mutual Fund"),
    NepseIndexSpec(67, "Investment Index", "Investment"),
)

INDEX_BY_OFFICIAL_ID: dict[int, NepseIndexSpec] = {spec.official_id: spec for spec in INDEX_REGISTRY}
INDEX_BY_NAME: dict[str, NepseIndexSpec] = {spec.name: spec for spec in INDEX_REGISTRY}
