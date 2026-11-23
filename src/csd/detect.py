"""Flag failure modes whose share of reports jumps above their recent baseline.

Counts are by month of the event (date_of_event), not the month FDA received the report, because
manufacturers sometimes file a backlog in one batch (in January 2026 one batch for this product added
about 56,000 reports of events from mid-2025). Shares, not raw counts, because the installed base grows.

For each mode m and month t:
    expected = share of m over the previous `baseline_months` months x reports in month t
    flag if observed >= min_count, observed / expected >= min_ratio, and the one-sided Poisson
    probability of seeing at least `observed` is below max_p_value.
A month is skipped until its reports are at least `min_completeness` of the baseline months' average,
because recent months fill in over the following weeks.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

DEFAULTS = {"baseline_months": 6, "min_count": 30, "min_ratio": 1.5, "max_p_value": 0.001, "min_completeness": 0.5}


@dataclass
class Signal:
    mode: str
    month: str
    observed: int
    expected: float
    ratio: float
    p_value: float
    share: float
    baseline_share: float
    completeness: float
    flagged: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("expected", "ratio", "share", "baseline_share", "completeness"):
            d[k] = round(d[k], 4)
        d["p_value"] = float(f"{self.p_value:.3g}")
        return d


def poisson_tail(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # sum the upper tail directly in log space, starting at k; terms shrink fast once i > lam
    log_term = -lam + k * math.log(lam) - math.lgamma(k + 1)
    total, i = 0.0, k
    while True:
        total += math.exp(log_term)
        i += 1
        log_term += math.log(lam) - math.log(i)
        if i > lam and math.exp(log_term) < 1e-18 * max(total, 1e-300):
            break
        if i - k > 200000:
            break
    return min(1.0, total)


def scan(series: dict[str, dict[str, int]], totals: dict[str, int], config: dict | None = None) -> list[Signal]:
    """Score every (mode, month) that has a full baseline. Returns all scored points, flagged or not."""
    cfg = {**DEFAULTS, **(config or {})}
    months = sorted(totals)
    out: list[Signal] = []
    b = cfg["baseline_months"]
    for i in range(b, len(months)):
        month, base = months[i], months[i - b : i]
        base_total = sum(totals[m] for m in base)
        if base_total == 0:
            continue
        completeness = totals[month] / (base_total / b)
        for mode, counts in series.items():
            base_count = sum(counts.get(m, 0) for m in base)
            p0 = base_count / base_total
            observed = counts.get(month, 0)
            expected = p0 * totals[month]
            ratio = observed / expected if expected > 0 else (math.inf if observed else 0.0)
            p = poisson_tail(observed, expected) if expected > 0 else (0.0 if observed else 1.0)
            flagged = (
                completeness >= cfg["min_completeness"]
                and observed >= cfg["min_count"]
                and ratio >= cfg["min_ratio"]
                and p <= cfg["max_p_value"]
            )
            share = observed / totals[month] if totals[month] else 0.0
            out.append(Signal(mode, month, observed, expected, ratio, p, share, p0, completeness, flagged))
    return out


def flags(series, totals, config=None) -> list[Signal]:
    return [s for s in scan(series, totals, config) if s.flagged]
