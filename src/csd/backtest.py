"""Replay the detector on what FDA had received by each date before a public event.

For each event and each weekly cutoff, run the detector on the counts known at that cutoff and record
whether the event's mode was flagged for any month in the six months before the cutoff.
"""

from __future__ import annotations

import datetime as dt

from .detect import scan


def months_before(day: str, n: int) -> str:
    d = dt.date.fromisoformat(day)
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def run_event(event: dict, config: dict | None = None) -> dict:
    timeline = []
    first = None
    for point in event["points"]:
        signals = scan({event["mode"]: point["mode"]}, point["with_narrative"], config)
        recent = [s for s in signals if s.month >= months_before(point["as_of"], 6)]
        hit = [s for s in recent if s.flagged]
        best = max(recent, key=lambda s: s.ratio if s.completeness >= 0.5 else 0, default=None)
        row = {
            "as_of": point["as_of"],
            "flagged": bool(hit),
            "flagged_months": [s.as_dict() for s in hit],
            "strongest": best.as_dict() if best else None,
        }
        timeline.append(row)
        if hit and first is None and point["as_of"] < event["date"]:
            first = row
    lead_days = None
    if first:
        lead_days = (dt.date.fromisoformat(event["date"]) - dt.date.fromisoformat(first["as_of"])).days
    return {
        "id": event["id"],
        "title": event["title"],
        "date": event["date"],
        "mode": event["mode"],
        "source": event["source"],
        "detail": event["detail"],
        "caught_before_event": first is not None,
        "first_flag_as_of": first["as_of"] if first else None,
        "lead_days": lead_days,
        "timeline": timeline,
    }


def run(backtest_doc: dict, config: dict | None = None) -> list[dict]:
    return [run_event(ev, config) for ev in backtest_doc["events"]]
