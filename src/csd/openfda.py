"""Small client for the openFDA device adverse event API (https://open.fda.gov/apis/device/event/).

Only the standard library, so the detector runs anywhere. Set OPENFDA_API_KEY for higher rate limits;
without a key openFDA allows 240 requests a minute and 1,000 a day per IP, which is enough for a snapshot.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "https://api.fda.gov/device/event.json"


class OpenFDA:
    def __init__(self, api_key: str | None = None, pause_s: float = 0.3, opener=None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENFDA_API_KEY", "")
        self.pause_s = pause_s
        self.opener = opener or urllib.request.urlopen
        self.requests = 0

    def get(self, search: str, **params) -> dict:
        """One API call. A search with no matches returns {"results": []} instead of raising."""
        query = {"search": search, **{k: str(v) for k, v in params.items()}}
        if self.api_key:
            query["api_key"] = self.api_key
        url = BASE + "?" + urllib.parse.urlencode(query, safe=':"[]+()*/')
        for attempt in range(4):
            try:
                self.requests += 1
                with self.opener(url, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
                time.sleep(self.pause_s)
                return data
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    return {"results": []}
                if err.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(2**attempt * 2)
                    continue
                raise
        raise RuntimeError("unreachable")

    def count_by_month(self, search: str, date_field: str = "date_of_event") -> dict[str, int]:
        """Reports per calendar month (YYYY-MM) of date_field, for every report matching search."""
        data = self.get(search, count=date_field)
        months: dict[str, int] = defaultdict(int)
        for row in data.get("results", []):
            t = row["time"]
            months[f"{t[:4]}-{t[4:6]}"] += row["count"]
        return dict(sorted(months.items()))

    def count_terms(self, search: str, field: str, limit: int = 100) -> dict[str, int]:
        data = self.get(search, count=field, limit=limit)
        return {row["term"]: row["count"] for row in data.get("results", [])}

    def reports(self, search: str, limit: int = 100, skip: int = 0) -> list[dict]:
        return self.get(search, limit=limit, skip=skip).get("results", [])

    def reports_by_number(self, numbers: list[str]) -> dict[str, dict]:
        """Fetch specific reports by report_number, 20 per request."""
        found: dict[str, dict] = {}
        for i in range(0, len(numbers), 20):
            chunk = numbers[i : i + 20]
            search = "report_number:(" + " OR ".join(f'"{n}"' for n in chunk) + ")"
            for rec in self.reports(search, limit=100):
                found.setdefault(rec["report_number"], rec)
        return found


def narrative(record: dict) -> str:
    """The event description text of a report (FDA's 'Description of Event or Problem')."""
    parts = [t.get("text", "") for t in record.get("mdr_text", []) if t.get("text_type_code", "").startswith("Desc")]
    return " ".join(" ".join(parts).split())


def date_range(start: str, end: str) -> str:
    """openFDA date range clause from YYYY-MM-DD dates."""
    return f"[{start.replace('-', '')} TO {end.replace('-', '')}]"
