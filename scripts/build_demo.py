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
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load(name, default=None):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def e(s) -> str:
    return html.escape(str(s))


def month_name(ym: str) -> str:
    y, m = ym.split("-")
    return MONTHS[int(m) - 1] + " " + y


def fmt_date(d: str) -> str:
    y, m, day = d.split("-")
    return f"{MONTHS[int(m) - 1]} {int(day)}, {y}"


def mode_chart(mode: str, months: list[str], pts: dict, flagged: set, events: list[dict], min_ratio: float) -> str:
    """Share of reports by event month for one mode, with its baseline and the flag bar, drawn to scale."""
    w, h, left, right, top, bottom = 1000, 330, 52, 20, 66, 34
    pw, ph = w - left - right, h - top - bottom
    shares = [pts[m]["share"] for m in months]
    bases = [pts[m]["baseline_share"] for m in months]
    ymax = max(max(shares), max(b * min_ratio for b in bases)) * 1.12 or 1
    step = 10 ** len(str(int(ymax * 100))) / 10 if ymax * 100 >= 1 else 0.1
    tick = max(step, round(ymax * 100 / 4 / step) * step)

    def x(i):
        return left + i * pw / max(1, len(months) - 1)

    def y(v):
        return top + ph - v / ymax * ph

    out = []
    v = 0.0
    while v <= ymax * 100 + 1e-9:
        yy = y(v / 100)
        out.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        out.append(f'<text x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end">{v:g}%</text>')
        v += tick
    band = " ".join(f"{x(i):.1f},{y(b * min_ratio):.1f}" for i, b in enumerate(bases))
    band += " " + " ".join(f"{x(i):.1f},{y(b):.1f}" for i, b in reversed(list(enumerate(bases))))
    out.append(f'<polygon class="band" points="{band}"/>')
    base_line = " ".join(f"{x(i):.1f},{y(b):.1f}" for i, b in enumerate(bases))
    out.append(f'<polyline class="base" points="{base_line}"/>')
    mine = sorted((ev for ev in events if ev["mode"] == mode and ev["date"][:7] in months), key=lambda ev: ev["date"])
    for k, ev in enumerate(mine):
        xx = x(months.index(ev["date"][:7]))
        anchor = "end" if xx > w * 0.7 else "start"
        dx = -5 if anchor == "end" else 5
        ty = 14 + 16 * (k % 3)
        out.append(f'<line class="ev" x1="{xx:.1f}" x2="{xx:.1f}" y1="{ty - 10}" y2="{top + ph}"/>')
        out.append(f'<text x="{xx + dx:.1f}" y="{ty}" text-anchor="{anchor}">FDA action, {e(ev["short"])}</text>')
    line = " ".join(f"{x(i):.1f},{y(s):.1f}" for i, s in enumerate(shares))
    out.append(f'<polyline class="share" points="{line}"/>')
    for i, m in enumerate(months):
        p = pts[m]
        if m in flagged:
            out.append(
                f'<rect class="flag" x="{x(i) - 5:.1f}" y="{y(p["share"]) - 5:.1f}" width="10" height="10" rx="2">'
                f"<title>{e(month_name(m))}: flagged, {p['ratio']:.1f}x baseline</title></rect>"
            )
            out.append(
                f'<text class="fl" x="{x(i):.1f}" y="{y(p["share"]) - 10:.1f}" text-anchor="middle">{p["ratio"]:.1f}x</text>'
            )
        elif p["completeness"] < 0.5:
            out.append(
                f'<circle class="open" cx="{x(i):.1f}" cy="{y(p["share"]):.1f}" r="3.5"><title>{e(month_name(m))}: still filling in</title></circle>'
            )
        else:
            out.append(f'<circle class="pt" cx="{x(i):.1f}" cy="{y(p["share"]):.1f}" r="2.5"/>')
        if i % 3 == 0 or i == len(months) - 1:
            out.append(f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle">{e(month_name(m))}</text>')
    label = f"{LABEL[mode]}: share of reports by event month, with its baseline"
    return f'<svg class="big" viewBox="0 0 {w} {h}" role="img" aria-label="{e(label)}">{"".join(out)}</svg>'


def spark(months: list[str], pts: dict, flagged: set) -> str:
    w, h, pad = 200, 44, 4
    shares = [pts[m]["share"] for m in months]
    bases = [pts[m]["baseline_share"] for m in months]
    top = max(shares + bases) * 1.1 or 1

    def xy(i, v):
        return f"{pad + i * (w - 2 * pad) / max(1, len(months) - 1):.1f},{h - pad - v / top * (h - 2 * pad):.1f}"

    dots = "".join(
        f'<rect class="flag" x="{float(xy(i, pts[m]["share"]).split(",")[0]) - 3:.1f}" '
        f'y="{float(xy(i, pts[m]["share"]).split(",")[1]) - 3:.1f}" width="6" height="6" rx="1"/>'
        for i, m in enumerate(months)
        if m in flagged
    )
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true">'
        f'<polyline class="base" points="{" ".join(xy(i, b) for i, b in enumerate(bases))}"/>'
        f'<polyline class="share" points="{" ".join(xy(i, s) for i, s in enumerate(shares))}"/>{dots}</svg>'
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
            f"<tr><td>{e(title)}</td><td><span class='badge {e(r['decision'])}'>{e(r['decision'].upper())}</span></td><td>{ok} of {n}</td>"
            f"<td>{free_ok} of {len(free)}</td><td>{crit}</td><td>{review}</td><td>{cost_s}</td><td>{lat_s}</td><td>{link}</td></tr>"
        )
        dst = DOCS / "eval" / key
        dst.mkdir(parents=True, exist_ok=True)
        if (REPORTS / key / "index.html").exists():
            shutil.copy(REPORTS / key / "index.html", dst / "index.html")
    return "".join(rows)


CSS = """
.head h1{margin:40px 0 14px}
.head .lead{max-width:42em}
.head .meta{margin:10px 0 0;font:400 13.5px/1.5 var(--mono);color:var(--ink-2)}
.board{margin:32px 0 0;border:1px solid var(--rule);border-radius:16px;background:#fbfaf6;overflow:hidden;scroll-margin-top:24px}
.vline{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 24px;align-items:center;padding:22px 24px 18px}
.vline h2{all:unset;display:block;font:400 34px/1.1 var(--serif)}
.vline p{grid-column:1/-1;margin:0;font-size:17px;max-width:48em}
.gate{justify-self:end;display:inline-flex;align-items:center;min-height:34px;padding:0 16px;border-radius:999px;font:500 13px/1 var(--mono);letter-spacing:.06em;white-space:nowrap}
.gate.nogo{background:var(--ink);color:var(--paper)}
.gate.go{background:var(--green-wash);color:var(--green)}
.score{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--rule)}
.score div{padding:16px 20px;font-size:14px;color:var(--ink-2);line-height:1.4}
.score div+div{border-left:1px solid var(--rule)}
.score b{display:block;font:400 30px/1.1 var(--serif);color:var(--ink);margin-bottom:4px;font-variant-numeric:tabular-nums}
.score b small{font-size:18px;color:var(--ink-2)}
.modes{border-top:1px solid var(--rule);padding:16px 24px 22px}
.modes .hint{margin:0 0 12px;color:var(--ink-2);font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px}
button.tile{display:flex;flex-direction:column;align-items:stretch;gap:6px;min-height:0;padding:0 14px 12px;border:1px solid var(--rule);border-radius:12px;background:var(--paper);color:var(--ink);text-align:left;font:inherit;font-weight:400;overflow:hidden;cursor:pointer;transition:border-color .2s,box-shadow .2s,transform .2s var(--ease)}
button.tile::before{content:"";display:block;height:5px;margin:0 -14px 4px;background:var(--rule-soft)}
button.tile.t-now::before{background:var(--ink)}
button.tile.t-past::before{background:repeating-linear-gradient(90deg,var(--ink) 0 8px,transparent 8px 12px)}
button.tile:hover{border-color:var(--ink);transform:translateY(-2px)}
button.tile[aria-expanded=true]{border-color:var(--ink);box-shadow:0 0 0 1.5px var(--ink)}
.tile .top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.tile .name{font:400 17px/1.2 var(--serif);min-height:2.4em}
.tile .nums{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;color:var(--ink-2)}
.tile .nums b{font:400 18px/1 var(--serif);color:var(--ink);margin-right:4px}
.badge{min-height:22px;padding:0 9px;font-size:11px}
.badge.past{border-style:dashed}
.safety{font:500 11px/1 var(--mono);letter-spacing:.03em;color:var(--ink-2)}
svg text{font:400 13px var(--mono);fill:var(--ink-2)}
.spark{display:block;width:100%;height:auto}
.spark .share,.big .share{fill:none;stroke:var(--ink);stroke-width:1.6;stroke-linejoin:round}
.spark .base,.big .base{fill:none;stroke:var(--green);stroke-width:1.3;stroke-dasharray:4 3}
.big .band{fill:var(--green-wash);opacity:.7}
.big .grid{stroke:var(--rule-soft)}
.big .ev{stroke:var(--ink-2);stroke-dasharray:2 3}
.flag{fill:var(--ink)}
.big .pt{fill:var(--ink)}
.big .open{fill:var(--paper);stroke:var(--ink);stroke-width:1.3}
.big text.fl{fill:var(--ink);font-weight:500}
.detail{border-top:1px solid var(--rule);padding:20px 24px 22px;background:var(--paper)}
.detail h3{margin:0 0 4px;font:400 24px/1.2 var(--serif)}
.detail .desc{margin:0 0 10px;color:var(--ink-2);font-size:15px;max-width:48em}
.big{display:block;width:100%;height:auto;overflow:visible}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0 0;font-size:13px;color:var(--ink-2)}
.key i{display:inline-block;width:18px;height:0;border-top:1.6px solid var(--ink);vertical-align:middle;margin-right:6px}
.key i.b{border-top:1.3px dashed var(--green)}
.key i.band{height:10px;border:0;background:var(--green-wash)}
.key i.sq{width:9px;height:9px;border:0;background:var(--ink);border-radius:2px}
.key i.ev{border-top:1.3px dotted var(--ink-2)}
.key i.op{width:8px;height:8px;border:1.3px solid var(--ink);border-radius:50%}
.sig{margin:16px 0 0;padding:14px 0 0;border-top:1px solid var(--rule-soft)}
.sig h4{margin:0 0 4px;font:500 16px/1.3 var(--sans)}
.sig p{margin:0;font-size:15px}
.ex{font-size:14px;color:var(--ink-2);padding-left:18px;margin:8px 0 0}
.ex li{margin:4px 0}
.mini{margin:12px 0 0;font-size:14px;color:var(--ink-2)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:56px;align-items:start}
.content h2{scroll-margin-top:24px}
.content h3{font:400 21px/1.25 var(--serif);margin:32px 0 8px}
.muted{color:var(--ink-2);font-size:15px;max-width:46em}
.side{position:sticky;top:24px;margin-top:64px;display:grid;gap:22px;font-size:14px;color:var(--ink-2)}
.side h3{margin:0 0 6px;font:500 13px/1.3 var(--sans);color:var(--ink)}
.side p{margin:0}
.side nav a{display:block;padding:5px 0;color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--rule-soft)}
.side nav a:hover{color:var(--ink)}
.side pre{font-size:12px;margin:6px 0 0}
.bt{list-style:none;margin:0;padding:0}
.bt li{display:grid;grid-template-columns:7.5em minmax(0,1fr) 9.5em;gap:6px 18px;padding:14px 0;border-top:1px solid var(--rule);margin:0}
.bt li:last-child{border-bottom:1px solid var(--rule)}
.bt .d{font:400 13px/1.5 var(--mono);color:var(--ink-2)}
.bt .t a{font-weight:500}
.bt .t span{display:block;color:var(--ink-2);font-size:14px;margin-top:2px}
.bt .r{grid-column:2/-1;font-size:15px}
.bt .res{justify-self:end;align-self:start}
@media (max-width:1000px){
 .layout{grid-template-columns:minmax(0,1fr);gap:0}
 .side{position:static;margin-top:48px}
 .score{grid-template-columns:repeat(2,minmax(0,1fr))}
 .score div:nth-child(3){border-left:0}
 .score div:nth-child(n+3){border-top:1px solid var(--rule)}
}
@media (max-width:700px){
 .vline,.modes,.detail{padding-left:16px;padding-right:16px}
 .vline h2{font-size:28px}
 .vline p{font-size:16px}
 .score div{padding:14px 16px}
 .score b{font-size:26px}
 .tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
 button.tile{padding:0 11px 10px}
 button.tile::before{margin:0 -11px 2px}
 .tile .name{font-size:15.5px}
 .tile .top{flex-wrap:wrap}
 .tile .nums{flex-direction:column;gap:2px}
 .chart{overflow-x:auto;margin:0 -16px;padding:0 16px}
 .big{min-width:700px}
 .big text{font-size:17px}
 .bt li{grid-template-columns:minmax(0,1fr) auto}
 .bt .t,.bt .r{grid-column:1/-1}
 .bt .res{grid-row:1;grid-column:2}
}
@media (prefers-reduced-motion:reduce){button.tile{transition:none}}
"""

JS = """
const tiles=[...document.querySelectorAll("button.tile")];
function pick(m){
  tiles.forEach(b=>b.setAttribute("aria-expanded",String(b.dataset.m===m)));
  document.querySelectorAll(".detail").forEach(d=>d.hidden=d.dataset.m!==m);
}
tiles.forEach(b=>b.addEventListener("click",()=>pick(b.dataset.m)));
"""


def main() -> None:
    series = load("series.json")
    signals = load("signals.json", {"points": [], "flagged": []})
    backtest = load("backtest_results.json", [])
    examples = load("examples.json", {})
    llm = load("llm_eval_tags.json")
    unexplained = load("unexplained.json")
    totals = series["with_narrative"]
    events = [{**ev, "short": fmt_date(ev["date"])} for ev in PRODUCT.events]
    min_ratio = PRODUCT.detection.get("min_ratio", 1.5)

    latest = sorted(totals)[-1]
    recent_cut = sorted(totals)[-7]
    recent = [p for p in signals["flagged"] if p["month"] >= recent_cut]
    recent_modes = {p["mode"] for p in recent}
    months = sorted({p["month"] for p in signals["points"]})
    pts = {md: {p["month"]: p for p in signals["points"] if p["mode"] == md} for md in PRODUCT.mode_ids}
    flagged_by_mode = {md: {p["month"] for p in signals["flagged"] if p["mode"] == md} for md in PRODUCT.mode_ids}
    n_reports = sum(series.get("all_reports", totals).values())
    caught = sum(1 for r in backtest if r["caught_before_event"])

    # Verdict
    if recent:
        top = max(recent, key=lambda p: (p["month"], p["ratio"]))
        n = len(recent_modes)
        verdict = f"{n} failure mode{'s' if n != 1 else ''} rising"
        gate = f'<span class="gate nogo">{n} RISING</span>'
        take = (
            f"<b>{e(LABEL[top['mode']])}, {e(month_name(top['month']))}:</b> {top['observed']:,} reports against "
            f"{top['expected']:,.0f} expected from the previous six months, {top['ratio']:.1f}x its baseline share. "
            f"Checked across {len(PRODUCT.modes)} failure modes, counted by the month the event happened, over the last six months of complete data."
        )
        first = top["mode"]
    else:
        verdict = "Nothing rising"
        gate = '<span class="gate go">QUIET</span>'
        take = "No mode is above its baseline in the last six months of complete data."
        first = max(PRODUCT.mode_ids, key=lambda md: len(flagged_by_mode[md]))

    def tile(md):
        mode = PRODUCT.mode(md)
        now, past = md in recent_modes, bool(flagged_by_mode[md])
        cls = "t-now" if now else "t-past" if past else ""
        badge = (
            '<span class="badge no-go">RISING</span>'
            if now
            else f'<span class="badge past">{len(flagged_by_mode[md])} flagged</span>'
            if past
            else ""
        )
        lastp = [pts[md][mm] for mm in months if pts[md][mm]["completeness"] >= 0.5][-1]
        return (
            f'<button type="button" class="tile {cls}" data-m="{md}" aria-expanded="{str(md == first).lower()}" aria-controls="det-{md}">'
            f'<span class="top"><span class="safety">{"SAFETY" if mode.safety else "&nbsp;"}</span>{badge}</span>'
            f'<span class="name">{e(mode.label)}</span>{spark(months, pts[md], flagged_by_mode[md])}'
            f'<span class="nums"><span><b>{lastp["share"] * 100:.1f}%</b>of reports, {e(month_name(lastp["month"]))}</span>'
            f"<span><b>{lastp['ratio']:.1f}x</b>baseline</span></span></button>"
        )

    def detail(md):
        mode = PRODUCT.mode(md)
        sigs = ""
        for p in sorted([p for p in recent if p["mode"] == md], key=lambda p: p["month"], reverse=True):
            ex = examples.get(f"{md}|{p['month']}", [])
            ex_html = "".join(
                f"<li><code>{e(x['report_number'])}</code> {e(x['narrative'][:220])}...</li>" for x in ex[:2]
            )
            sigs += (
                f"<div class='sig'><h4>Rising now: {e(month_name(p['month']))}</h4>"
                f"<p>{p['observed']:,} reports against {p['expected']:,.0f} expected from the previous six months "
                f"({p['share'] * 100:.1f}% of reports vs {p['baseline_share'] * 100:.1f}%), {p['ratio']:.1f}x, "
                f"Poisson p {p['p_value']:.1g}.</p><ul class='ex'>{ex_html}</ul></div>"
            )
        hist = [p for p in signals["flagged"] if p["mode"] == md]
        hist_s = (
            "Flagged on today's data: "
            + ", ".join(f"{month_name(p['month'])} ({p['ratio']:.1f}x)" for p in sorted(hist, key=lambda p: p["month"]))
            + "."
            if hist
            else "Never flagged on today's data."
        )
        bts = [r for r in backtest if r["mode"] == md]
        bt_s = ""
        if bts:
            bt_s = (
                " Backtest: "
                + "; ".join(
                    f"{r['title']}, {'flagged ' + str(r['lead_days']) + ' days before' if r['caught_before_event'] else 'not flagged before'}"
                    for r in sorted(bts, key=lambda r: r["date"])
                )
                + "."
            )
        return (
            f'<div class="detail" id="det-{md}" data-m="{md}"{"" if md == first else " hidden"}>'
            f"<h3>{e(mode.label)}</h3><p class='desc'>{e(mode.description)}</p>"
            f'<div class="chart">{mode_chart(md, months, pts[md], flagged_by_mode[md], events, min_ratio)}</div>'
            f'<p class="key"><span><i></i>share of reports</span><span><i class="b"></i>baseline (previous six months)</span>'
            f'<span><i class="band"></i>up to {min_ratio:g}x baseline</span><span><i class="sq"></i>flagged month</span>'
            f'<span><i class="op"></i>month still filling in</span><span><i class="ev"></i>public FDA action</span></p>'
            f"{sigs}<p class='mini'>{e(hist_s)}{e(bt_s)}</p></div>"
        )

    order = sorted(
        PRODUCT.mode_ids, key=lambda md: (md not in recent_modes, not flagged_by_mode[md], PRODUCT.mode_ids.index(md))
    )
    tiles_html = "".join(tile(md) for md in order)
    details_html = "".join(detail(md) for md in order)

    bt_html = ""
    for r in sorted(backtest, key=lambda r: r["date"]):
        if r["caught_before_event"]:
            badge = f'<span class="badge go">{r["lead_days"]} days early</span>'
            res = f"<b>Flagged {r['lead_days']} days before</b> (as of {fmt_date(r['first_flag_as_of'])})"
            fm = r["timeline"][[t["as_of"] for t in r["timeline"]].index(r["first_flag_as_of"])]["flagged_months"][0]
            res += f": {month_name(fm['month'])} at {fm['ratio']:.1f}x its baseline share."
        else:
            badge = '<span class="badge no-go">missed</span>'
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
            f"<li><span class='d'>{fmt_date(r['date'])}</span><span class='t'><a href='{e(r['source'])}'>{e(r['title'])}</a>"
            f"<span>{e(LABEL[r['mode']])}. {e(r['detail'])}</span></span><span class='res'>{badge}</span>"
            f"<span class='r'>{res}</span></li>"
        )

    hist_rows = "".join(
        f"<tr><td>{e(month_name(p['month']))}</td><td>{e(LABEL[p['mode']])}</td><td class='num'>{p['observed']:,}</td>"
        f"<td class='num'>{p['expected']:,.0f}</td><td class='num'>{p['ratio']:.1f}x</td></tr>"
        for p in sorted(signals["flagged"], key=lambda p: p["month"])
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
            f'<h2 id="misses">What the rules miss</h2><p>Each run, Claude reads recent reports the phrase rules cannot place. '
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
    n_cases = (
        len(json.loads((ROOT / "eval" / "cases.json").read_text())["cases"])
        if (ROOT / "eval" / "cases.json").exists()
        else 0
    )
    nav = [
        ("board", "Failure modes"),
        ("backtest", "Backtest"),
        ("history", "Every month flagged"),
        ("eval", "Tagging eval"),
    ]
    if unexplained:
        nav.append(("misses", "What the rules miss"))
    nav.append(("how", "How it works"))

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Complaint signal detector</title>
<meta name="description" content="Public FDA adverse event reports for the {e(PRODUCT.name)}, scanned month by month for failure modes rising above their baseline.">
<style>{CSS}</style></head><body><main>
<div class="head">
<h1>Complaint signal detector</h1>
<p class="lead">Public FDA adverse event reports for the {e(PRODUCT.name)}, scanned for failure modes that are rising above their own baseline.</p>
<p class="meta">Data from openFDA, last updated {e(series["openfda_last_updated"])}. Events {e(month_name(sorted(totals)[0]))} to {e(month_name(latest))}.</p>
</div>

<section class="board" id="board" aria-labelledby="verdict-h">
  <div class="vline"><h2 id="verdict-h">{e(verdict)}</h2>{gate}<p>{take}</p></div>
  <div class="score">
    <div><b>{n_reports:,}</b>reports, events {e(month_name(sorted(totals)[0]))} to {e(month_name(latest))}</div>
    <div><b>{len(PRODUCT.modes)}</b>failure modes tracked</div>
    <div><b>{len(signals["flagged"])}</b>months flagged on today's data</div>
    <div><b>{caught} <small>of {len(backtest)}</small></b>public FDA actions flagged beforehand</div>
  </div>
  <div class="modes">
    <p class="hint">Each tile is one failure mode: its share of reports by event month (solid) against its baseline (dashed). Select one to see it in full.</p>
    <div class="tiles">{tiles_html}</div>
  </div>
  {details_html}
</section>

<div class="layout">
<div class="content">

<h2 id="backtest">Backtest: would it have seen it coming?</h2>
<p class="muted">For each public FDA action, the detector is replayed weekly for the 12 weeks before it, on only the reports FDA had received by each date. A flag counts only if it is on one of the three event months before that date, so a spike from an earlier issue is not credited to a later one.</p>
<ul class="bt">{bt_html}</ul>
<p class="muted">Public reports reach FDA up to 30 days after the manufacturer hears of an event, and recent months fill in slowly.
A manufacturer's own complaint feed sees the same reports weeks earlier, which is where this detector belongs.
A flag shows that a complaint type rose, not what caused it, and lead time is measured against the public start date of each action.
False alarms are not measured here: the replay scans only each action's own mode (see the flag history below).</p>

<h2 id="history">Every month flagged on today's data</h2>
<p class="muted">Unlike the backtest, this uses every report received since, so it shows what the detector sees in hindsight.
The inserter and applicator rise in early 2025 matches what Dexcom described on its October 2025 earnings call.</p>
<div class="scroll"><table><thead><tr><th>Event month</th><th>Mode</th><th class="num">Reports</th><th class="num">Expected</th><th class="num">Ratio</th></tr></thead><tbody>{hist_rows}</tbody></table></div>

<h2 id="eval">Tagging eval</h2>
<p class="muted">{n_cases} real reports, each labeled by hand with one failure mode, scored with <a href="https://github.com/pg2342-hub/golive-gate">golive-gate</a>.
Gate: at least 90% right overall and 80% on free-text reports, and no safety report (alerts, inaccurate readings, skin reactions)
filed under another mode. {llm_note}</p>
<div class="scroll"><table><thead><tr><th>Tagger</th><th>Gate</th><th>Right</th><th>Free text</th><th>Safety misses</th><th>To a person</th><th>Cost</th><th>Latency</th><th></th></tr></thead>
<tbody>{eval_rows()}</tbody></table></div>
<p class="muted">Read the rules row with care: the free-text reports were found by searching for known complaint wording, so the rules
do better here than on wording they have never seen (see below). The guardrails send some answers the model had right to a person:
that is the price of never filing a safety report under the wrong mode. The guardrails were fixed after an earlier run on
this same set, so treat the guardrail row as tuned, not held out. The model's answers vary a little between runs
(75 and 76 of 76 raw across the runs so far), which is why CI re-scores the recorded answers on every change.</p>
{unexp}

<h2 id="how">How it works</h2>
<ol>
<li><b>Count.</b> Each failure mode is a list of phrases (the manufacturer's allegation wording and consumers' own words). openFDA counts every matching report by event month, server-side.</li>
<li><b>Detect.</b> A mode is flagged when its share of reports is at least 1.5x its previous six months, with at least 30 reports and a Poisson p below 0.001. Months wait until half their usual reports have arrived.</li>
<li><b>Tag.</b> Claude reads narratives the phrases cannot place and picks a mode with a quote as evidence. Guardrails: the mode must exist, the quote must be in the text, low confidence goes to a person, and when the manufacturer's allegation sentence names a known mode, that mode wins.</li>
<li><b>Gate.</b> The tagger only ships if it passes the eval gate in CI.</li>
</ol>
<p class="muted">Limits: openFDA narratives are blank for many of the latest reports, which can hide a rise but not create one. Report counts are not failure rates. This page reads public data only and says nothing about causes.</p>
</div>

<aside class="side" aria-label="About this build">
  <nav aria-label="On this page">{"".join(f'<a href="#{i}">{t}</a>' for i, t in nav)}</nav>
  <div><h3>Data</h3><p>Public adverse event reports from openFDA, last updated {e(series["openfda_last_updated"])}, pulled {e(fmt_date(series["pulled_on"]))}. Counted by the month the event happened.</p></div>
  <div><h3>Run it yourself</h3><p>Python 3.10 or later. From the repo folder:</p><pre>pip install -e ".[claude]"
csd snapshot &amp;&amp; csd detect &amp;&amp; csd backtest
golive run eval/golive.yml --agent agent:rules_agent</pre></div>
  <div><a class="pill" href="{REPO}">Code on GitHub</a></div>
</aside>
</div>
</main>
<script>{JS}</script>
</body></html>"""
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(page)
    (DOCS / ".nojekyll").write_text("")
    import subprocess

    pages = [str(DOCS / "index.html")] + [str(p) for p in sorted(DOCS.glob("eval/*/index.html"))]
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_chrome.py"), *pages, "--repo", "complaint-signal-detector"],
        check=True,
    )
    print("wrote docs/index.html")


if __name__ == "__main__":
    main()
