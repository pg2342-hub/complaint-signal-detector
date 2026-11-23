"""Build docs/index.html (the GitHub Pages demo) from the files in data/ and reports/."""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from csd.taxonomy import load_product  # noqa: E402

DATA, DOCS, REPORTS = ROOT / "data", ROOT / "docs", ROOT / "reports"
PRODUCT = load_product(ROOT / "config" / "dexcom_g7.yml")
LABEL = {m.id: m.label for m in PRODUCT.modes} | {"other": "Other", "needs_review": "Sent to a person"}
REPO = "https://github.com/pg2342-hub/complaint-signal-detector"


def load(name, default=None):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def e(s) -> str:
    return html.escape(str(s))


def month_name(ym: str) -> str:
    y, m = ym.split("-")
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(m) - 1] + " " + y


def fmt_date(d: str) -> str:
    y, m, day = d.split("-")
    return f"{month_name(y + '-' + m).split()[0]} {int(day)}, {y}"


def sparkline(series: dict, totals: dict, points: list[dict], mode: str, events: list[dict]) -> str:
    months = sorted(totals)
    shares = [series.get(m, 0) / totals[m] if totals[m] else 0 for m in months]
    w, h, pad = 560, 120, 6
    top = max(shares) * 1.1 or 1
    xs = [pad + i * (w - 2 * pad) / max(1, len(months) - 1) for i in range(len(months))]
    ys = [h - pad - s / top * (h - 2 * pad) for s in shares]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    flagged = {p["month"] for p in points if p["mode"] == mode and p["flagged"]}
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#000"><title>{e(month_name(m))}: flagged</title></circle>'
        for x, y, m in zip(xs, ys, months, strict=True)
        if m in flagged
    )
    marks = ""
    for ev in events:
        if ev["mode"] != mode:
            continue
        ym = ev["date"][:7]
        if ym in months:
            x = xs[months.index(ym)]
            marks += (
                f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" stroke="#000" stroke-dasharray="3,3"/>'
                f'<text x="{x + 3:.1f}" y="11" font-size="10">{e(ev["short"])}</text>'
            )
    first, last = month_name(months[0]), month_name(months[-1])
    return (
        f'<svg viewBox="0 0 {w} {h + 16}" role="img" aria-label="{e(LABEL[mode])} share by month">'
        f'<polyline points="{line}" fill="none" stroke="#000" stroke-width="1.5"/>{dots}{marks}'
        f'<text x="{pad}" y="{h + 14}" font-size="10">{first}</text>'
        f'<text x="{w - pad}" y="{h + 14}" font-size="10" text-anchor="end">{last}</text></svg>'
    )


def eval_rows() -> str:
    rows = []
    names = [("rules", "Rules alone"), ("llm", "Claude, raw answer"), ("hybrid", "Claude with guardrails")]
    for key, title in names:
        p = REPORTS / key / "results.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())
        cases = r["cases"]
        n = len(cases)
        ok = sum(c["runs"][0]["passed"] for c in cases)
        free = [c for c in cases if c["group"] == "free_text"]
        free_ok = sum(c["runs"][0]["passed"] for c in free)
        crit = r["summary"]["by_run"][0]["critical"]
        review = sum(1 for c in cases if (c["runs"][0].get("output") or {}).get("mode") == "needs_review")
        cost = r["summary"]["total_cost_usd"] / n if n else 0
        lat = [((c["runs"][0].get("output") or {}).get("latency_s") or 0) for c in cases]
        lat_s = f"{sum(lat) / len(lat):.2f} s" if any(lat) else "none"
        cost_s = f"${cost * 1000:.3f} per 1,000" if cost else "free"
        link = f'<a href="eval/{key}/">every case</a>'
        rows.append(
            f"<tr><td>{e(title)}</td><td><b>{e(r['decision'].upper())}</b></td><td>{ok} of {n}</td>"
            f"<td>{free_ok} of {len(free)}</td><td>{crit}</td><td>{review}</td><td>{cost_s}</td><td>{lat_s}</td><td>{link}</td></tr>"
        )
        dst = DOCS / "eval" / key
        dst.mkdir(parents=True, exist_ok=True)
        if (REPORTS / key / "index.html").exists():
            shutil.copy(REPORTS / key / "index.html", dst / "index.html")
    return "".join(rows)


def main() -> None:
    series = load("series.json")
    signals = load("signals.json", {"points": [], "flagged": []})
    backtest = load("backtest_results.json", [])
    examples = load("examples.json", {})
    llm = load("llm_eval_tags.json")
    unexplained = load("unexplained.json")
    totals = series["with_narrative"]
    events = [{**ev, "short": fmt_date(ev["date"])} for ev in PRODUCT.events]

    latest = sorted(totals)[-1]
    recent_cut = sorted(totals)[-7]
    recent = [p for p in signals["flagged"] if p["month"] >= recent_cut]
    sig_html = ""
    for p in sorted(recent, key=lambda p: (p["month"], -p["ratio"]), reverse=True):
        ex = examples.get(f"{p['mode']}|{p['month']}", [])
        ex_html = "".join(f"<li><code>{e(x['report_number'])}</code> {e(x['narrative'][:220])}...</li>" for x in ex[:2])
        sig_html += (
            f"<div class='card'><h3>{e(LABEL[p['mode']])}, {e(month_name(p['month']))}</h3>"
            f"<p>{p['observed']:,} reports against {p['expected']:,.0f} expected from the previous six months "
            f"({p['share'] * 100:.1f}% of reports vs {p['baseline_share'] * 100:.1f}%), {p['ratio']:.1f}x, "
            f"Poisson p {p['p_value']:.1g}.</p><ul class='ex'>{ex_html}</ul></div>"
        )
    if not sig_html:
        sig_html = "<p>No mode is above its baseline in the last six months of complete data.</p>"

    bt_html = ""
    for r in sorted(backtest, key=lambda r: r["date"]):
        if r["caught_before_event"]:
            res = f"<b>Flagged {r['lead_days']} days before</b> (as of {fmt_date(r['first_flag_as_of'])})"
            fm = r["timeline"][[t["as_of"] for t in r["timeline"]].index(r["first_flag_as_of"])]["flagged_months"][0]
            res += f": {month_name(fm['month'])} at {fm['ratio']:.1f}x its baseline share."
        else:
            best = max(
                (t["strongest"] for t in r["timeline"] if t["strongest"] and t["as_of"] <= r["date"]),
                key=lambda x: x["ratio"],
                default=None,
            )
            res = "<b>Not flagged before the event.</b>"
            if best:
                res += (
                    f" Strongest sign in the window: {month_name(best['month'])} at {best['ratio']:.1f}x its baseline share"
                    f" ({best['observed']:,} reports), short of the flag bar."
                )
        bt_html += (
            f"<tr><td>{fmt_date(r['date'])}</td><td><a href='{e(r['source'])}'>{e(r['title'])}</a><br>"
            f"<span class='muted'>{e(r['detail'])}</span></td><td>{e(LABEL[r['mode']])}</td><td>{res}</td></tr>"
        )

    hist_rows = "".join(
        f"<tr><td>{e(month_name(p['month']))}</td><td>{e(LABEL[p['mode']])}</td><td>{p['observed']:,}</td>"
        f"<td>{p['expected']:,.0f}</td><td>{p['ratio']:.1f}x</td></tr>"
        for p in sorted(signals["flagged"], key=lambda p: p["month"])
    )
    flagged_modes = {p["mode"] for p in recent} | {r["mode"] for r in backtest}
    charts = "".join(
        f"<div class='chart'><h4>{e(LABEL[m])}: share of reports by event month</h4>"
        f"{sparkline(series['modes'][m], totals, signals['points'], m, events)}</div>"
        for m in PRODUCT.mode_ids
        if m in flagged_modes
    )

    llm_note = (
        f"Recorded run: {e(llm['model'])} on {fmt_date(llm['tagged_on'])}."
        if llm
        else "The Claude rows appear after the first run with an API key."
    )
    unexp = ""
    if unexplained:
        counts = {}
        for t in unexplained["tags"].values():
            counts[t["hybrid"]["mode"]] = counts.get(t["hybrid"]["mode"], 0) + 1
        dist = ", ".join(f"{LABEL.get(k, k)} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
        unexp = (
            f"<h2>What the rules miss</h2><p>Each run, Claude reads recent reports the phrase rules cannot place. "
            f"{e(month_name(unexplained['month']))}: {unexplained['sampled']} reports sampled, "
            f"{unexplained['rules_unplaced']} not placed by the rules. Claude, after guardrails: {e(dist)}. "
            f"New wording that keeps showing up becomes a new phrase, after a person reviews it.</p>"
        )
    if PRODUCT.phrase_log:
        items = "".join(
            f"<li>{fmt_date(p['date'])}: <code>{e(p['phrase'])}</code> added to {e(LABEL[p['mode']])}. {e(p['note'])}</li>"
            for p in PRODUCT.phrase_log
        )
        unexp += f"<h3>Phrases added after review</h3><ul>{items}</ul>"

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Complaint signal detector</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body{{font-family:Inter,system-ui,sans-serif;color:#000;background:#fff;max-width:900px;margin:0 auto;padding:24px 16px 64px;line-height:1.5}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:20px;margin:36px 0 8px;border-bottom:2px solid #000;padding-bottom:4px}}
h3{{font-size:16px;margin:0 0 6px}} h4{{font-size:13px;margin:0 0 4px;font-weight:600}}
a{{color:#000}} .muted{{color:#555;font-size:13px}} code{{font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border-bottom:1px solid #ccc;padding:8px 6px;text-align:left;vertical-align:top}}
.card{{border:1px solid #000;padding:12px 14px;margin:10px 0}} .ex{{font-size:12px;color:#333;padding-left:18px}}
.chart{{margin:14px 0}} svg{{width:100%;height:auto;max-width:600px}} .wrap{{overflow-x:auto}}
.kpi{{display:flex;gap:24px;flex-wrap:wrap;margin:12px 0}} .kpi div{{border-left:3px solid #000;padding-left:10px}}
.kpi b{{display:block;font-size:22px}}
</style></head><body>
<h1>Complaint signal detector</h1>
<p class="muted">Public FDA adverse event reports for the {e(PRODUCT.name)}, scanned for failure modes that are rising.
Data from openFDA, last updated {e(series["openfda_last_updated"])}. <a href="{REPO}">Code on GitHub</a>.</p>

<div class="kpi"><div><b>{sum(series.get("all_reports", totals).values()):,}</b>reports, events {e(month_name(sorted(totals)[0]))} to {e(month_name(latest))}</div>
<div><b>{len(PRODUCT.modes)}</b>failure modes tracked</div>
<div><b>{sum(1 for r in backtest if r["caught_before_event"])} of {len(backtest)}</b>public FDA actions flagged beforehand</div></div>

<h2>Rising now</h2>
<p class="muted">Modes above their baseline share in the last six months, counted by the month the event happened.</p>
{sig_html}

<h2>Backtest: would it have seen it coming?</h2>
<p class="muted">For each public FDA action, the detector is replayed weekly for the 12 weeks before it, on only the reports FDA had received by each date. A flag counts only if it is on one of the three event months before that date, so a spike from an earlier issue is not credited to a later one.</p>
<div class="wrap"><table><tr><th>Date</th><th>FDA action</th><th>Mode</th><th>Result</th></tr>{bt_html}</table></div>
<p>Public reports reach FDA up to 30 days after the manufacturer hears of an event, and recent months fill in slowly.
A manufacturer's own complaint feed sees the same reports weeks earlier, which is where this detector belongs.
A flag shows that a complaint type rose, not what caused it, and lead time is measured against the public start date of each action.
False alarms are not measured here: the replay scans only each action's own mode (see the flag history below).</p>
{charts}
<h3>Every month flagged on today's data</h3>
<p class="muted">Unlike the backtest, this uses every report received since, so it shows what the detector sees in hindsight.
The inserter and applicator rise in early 2025 matches what Dexcom described on its October 2025 earnings call.</p>
<div class="wrap"><table><tr><th>Event month</th><th>Mode</th><th>Reports</th><th>Expected</th><th>Ratio</th></tr>{hist_rows}</table></div>

<h2>Tagging eval</h2>
<p class="muted">{len(json.loads((ROOT / "eval" / "cases.json").read_text())["cases"]) if (ROOT / "eval" / "cases.json").exists() else 0} real reports,
each labeled by hand with one failure mode, scored with <a href="https://github.com/pg2342-hub/golive-gate">golive-gate</a>.
Gate: at least 90% right overall and 80% on free-text reports, and no safety report (alerts, inaccurate readings, skin reactions)
filed under another mode. {llm_note}</p>
<p class="muted">Read the rules row with care: the free-text reports were found by searching for known complaint wording, so the rules
do better here than on wording they have never seen (see below). The guardrails send some answers the model had right to a person:
that is the price of never filing a safety report under the wrong mode. The guardrails were fixed after an earlier run on
this same set, so treat the guardrail row as tuned, not held out. The model's answers vary a little between runs
(75 and 76 of 76 raw across the runs so far), which is why CI re-scores the recorded answers on every change.</p>
<div class="wrap"><table><tr><th>Tagger</th><th>Gate</th><th>Right</th><th>Free text</th><th>Safety misses</th><th>To a person</th><th>Cost</th><th>Latency</th><th></th></tr>
{eval_rows()}</table></div>
{unexp}

<h2>How it works</h2>
<ol>
<li><b>Count.</b> Each failure mode is a list of phrases (the manufacturer's allegation wording and consumers' own words). openFDA counts every matching report by event month, server-side.</li>
<li><b>Detect.</b> A mode is flagged when its share of reports is at least 1.5x its previous six months, with at least 30 reports and a Poisson p below 0.001. Months wait until half their usual reports have arrived.</li>
<li><b>Tag.</b> Claude reads narratives the phrases cannot place and picks a mode with a quote as evidence. Guardrails: the mode must exist, the quote must be in the text, low confidence goes to a person, and when the manufacturer's allegation sentence names a known mode, that mode wins.</li>
<li><b>Gate.</b> The tagger only ships if it passes the eval gate in CI.</li>
</ol>
<p class="muted">Limits: openFDA narratives are blank for many of the latest reports, which can hide a rise but not create one. Report counts are not failure rates. This page reads public data only and says nothing about causes.</p>
<pre style="font-size:12px;background:#f4f4f4;padding:10px;overflow-x:auto">pip install -e ".[claude]"
csd snapshot &amp;&amp; csd detect &amp;&amp; csd backtest
golive run eval/golive.yml --agent agent:rules_agent</pre>
</body></html>"""
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page)
    (DOCS / ".nojekyll").write_text("")
    print("wrote docs/index.html")


if __name__ == "__main__":
    main()
