"""csd: command line for the complaint signal detector.

csd snapshot    pull counts, backtest counts and eval narratives from openFDA into data/
csd detect      score every mode and month in data/series.json, write data/signals.json
csd backtest    replay the detector before each public event, write data/backtest_results.json
csd examples    fetch three example narratives for each current signal, write data/examples.json
csd tag-eval    run the Claude tagger on every eval narrative, write data/llm_eval_tags.json (needs ANTHROPIC_API_KEY)
csd unexplained tag a sample of recent narratives the rules cannot place, write data/unexplained.json (needs key)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import backtest as bt
from .detect import scan
from .openfda import OpenFDA, date_range, narrative
from .snapshot import take
from .tagger import ClaudeTagger, guard, rules_tag
from .taxonomy import OTHER, load_product

ROOT = Path.cwd()


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1))
    print(f"wrote {path}")


def cmd_snapshot(a) -> None:
    product = load_product(a.config)
    end = a.end or dt.date.today().isoformat()
    print(json.dumps(take(OpenFDA(), product, Path(a.data), a.start, end, Path(a.labels)), indent=1))


def current_signals(product, series: dict) -> list[dict]:
    points = scan(series["modes"], series["with_narrative"], product.detection)
    return [p.as_dict() for p in points]


def cmd_detect(a) -> None:
    product = load_product(a.config)
    series = _load(Path(a.data) / "series.json")
    points = current_signals(product, series)
    flagged = [p for p in points if p["flagged"]]
    _write(
        Path(a.data) / "signals.json", {"as_of": series["openfda_last_updated"], "points": points, "flagged": flagged}
    )
    for p in flagged:
        print(
            f"FLAG {p['mode']:22s} {p['month']}  {p['observed']:>6} vs {p['expected']:>8.1f} expected  x{p['ratio']:.2f}"
        )


def cmd_backtest(a) -> None:
    product = load_product(a.config)
    results = bt.run(_load(Path(a.data) / "backtest.json"), product.detection)
    _write(Path(a.data) / "backtest_results.json", results)
    for r in results:
        verdict = (
            f"flagged {r['lead_days']} days before" if r["caught_before_event"] else "not flagged before the event"
        )
        print(f"{r['date']}  {r['title']}: {verdict}")


def cmd_examples(a) -> None:
    product = load_product(a.config)
    api = OpenFDA()
    signals = _load(Path(a.data) / "signals.json")["flagged"]
    out = {}
    for s in signals:
        y, m = map(int, s["month"].split("-"))
        last = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        search = f"{product.search} AND date_of_event:{date_range(s['month'] + '-01', last)} AND {product.mode(s['mode']).openfda_query()}"
        recs = api.reports(search, limit=3)
        out[f"{s['mode']}|{s['month']}"] = [
            {
                "report_number": r["report_number"],
                "date_of_event": r.get("date_of_event"),
                "narrative": narrative(r)[:600],
            }
            for r in recs
        ]
    _write(Path(a.data) / "examples.json", out)


def cmd_tag_eval(a) -> None:
    product = load_product(a.config)
    reports = _load(Path(a.data) / "eval_reports.json")
    tagger = ClaudeTagger(product, model=a.model)
    out = {"model": a.model, "tagged_on": dt.date.today().isoformat(), "tags": {}}
    for n, rec in reports.items():
        raw = tagger(rec["narrative"])
        out["tags"][n] = {"llm": raw.as_dict(), "hybrid": guard(product, rec["narrative"], raw).as_dict()}
        print(f"{n}: {raw.mode} -> {out['tags'][n]['hybrid']['mode']}")
    _write(Path(a.data) / "llm_eval_tags.json", out)


def cmd_unexplained(a) -> None:
    """The model's second job: read what the rules cannot place, so new failure wording shows up."""
    product = load_product(a.config)
    series = _load(Path(a.data) / "series.json")
    month = a.month or sorted(series["with_narrative"])[-3]
    y, m = map(int, month.split("-"))
    last = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
    api = OpenFDA()
    recs = []
    for skip in range(0, a.sample, 100):
        recs += api.reports(
            f"{product.search} AND date_of_event:{date_range(month + '-01', last)} AND _exists_:mdr_text.text",
            limit=min(100, a.sample - skip),
            skip=skip,
        )
    texts = {r["report_number"]: narrative(r) for r in recs}
    unplaced = {n: t for n, t in texts.items() if rules_tag(product, t).mode == OTHER}
    tagger = ClaudeTagger(product, model=a.model)
    tags = {}
    for n, t in unplaced.items():
        raw = tagger(t)
        tags[n] = {"narrative": t[:400], "llm": raw.as_dict(), "hybrid": guard(product, t, raw).as_dict()}
    _write(
        Path(a.data) / "unexplained.json",
        {"month": month, "sampled": len(texts), "rules_unplaced": len(unplaced), "model": a.model, "tags": tags},
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="csd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config/dexcom_g7.yml")
    p.add_argument("--data", default="data")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--start", default="2024-07-01")
    s.add_argument("--end")
    s.add_argument("--labels", default="eval/labels.csv")
    s.set_defaults(fn=cmd_snapshot)
    sub.add_parser("detect").set_defaults(fn=cmd_detect)
    sub.add_parser("backtest").set_defaults(fn=cmd_backtest)
    sub.add_parser("examples").set_defaults(fn=cmd_examples)
    t = sub.add_parser("tag-eval")
    t.add_argument("--model", default="claude-haiku-5-5")
    t.set_defaults(fn=cmd_tag_eval)
    u = sub.add_parser("unexplained")
    u.add_argument("--month")
    u.add_argument("--sample", type=int, default=200)
    u.add_argument("--model", default="claude-haiku-5-5")
    u.set_defaults(fn=cmd_unexplained)
    args = p.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
