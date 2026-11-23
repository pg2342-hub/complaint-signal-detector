"""Pull everything the detector, the backtest and the eval need from openFDA, and save it as JSON.

data/series.json    reports by event month: all reports, reports with a narrative, and each mode
data/backtest.json  the same counts as FDA had them on each date before each public event
data/eval_reports.json  the narratives of the hand-labeled eval reports
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from .openfda import OpenFDA, date_range, narrative
from .taxonomy import Product

HAS_TEXT = "_exists_:mdr_text.text"


def month_series(
    api: OpenFDA, product: Product, start: str, end: str, received_by: str | None = None, only_mode: str | None = None
) -> dict:
    window = f"date_of_event:{date_range(start, end)}"
    if received_by:
        window += f" AND date_received:{date_range('2020-01-01', received_by)}"
    base = f"{product.search} AND {window}"
    modes = [product.mode(only_mode)] if only_mode else product.modes
    out = {
        "with_narrative": api.count_by_month(f"{base} AND {HAS_TEXT}"),
        "modes": {m.id: api.count_by_month(f"{base} AND {m.openfda_query()}") for m in modes},
    }
    if not only_mode:
        out["all_reports"] = api.count_by_month(base)
    return out


def cutoffs(event_date: str, weeks_before: int = 12) -> list[str]:
    d = dt.date.fromisoformat(event_date)
    return [(d - dt.timedelta(weeks=w)).isoformat() for w in range(weeks_before, -1, -1)]


def take(api: OpenFDA, product: Product, out_dir: Path, start: str, end: str, labels_csv: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = api.get(product.search, limit=1).get("meta", {})
    series = month_series(api, product, start, end)
    series_doc = {
        "product": product.name,
        "search": product.search,
        "openfda_last_updated": meta.get("last_updated"),
        "pulled_on": dt.date.today().isoformat(),
        "event_months": [start[:7], end[:7]],
        **series,
    }
    (out_dir / "series.json").write_text(json.dumps(series_doc, indent=1))

    backtest = {"pulled_on": series_doc["pulled_on"], "events": []}
    for ev in product.events:
        ev_start = (dt.date.fromisoformat(ev["date"]) - dt.timedelta(days=500)).isoformat()[:8] + "01"
        points = []
        for cut in cutoffs(ev["date"]):
            s = month_series(api, product, ev_start, cut, received_by=cut, only_mode=ev["mode"])
            points.append({"as_of": cut, "with_narrative": s["with_narrative"], "mode": s["modes"][ev["mode"]]})
        backtest["events"].append({**ev, "points": points})
    (out_dir / "backtest.json").write_text(json.dumps(backtest, indent=1))

    numbers = [row["report_number"] for row in csv.DictReader(labels_csv.open())]
    found = api.reports_by_number(numbers)
    reports = {
        n: {
            "date_of_event": found[n].get("date_of_event"),
            "date_received": found[n].get("date_received"),
            "product_problems": found[n].get("product_problems", []),
            "narrative": narrative(found[n]),
        }
        for n in numbers
        if n in found
    }
    (out_dir / "eval_reports.json").write_text(json.dumps(reports, indent=1))
    return {"requests": api.requests, "eval_reports": len(reports), "missing": sorted(set(numbers) - set(reports))}
