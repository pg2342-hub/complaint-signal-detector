# complaint-signal-detector

[![CI](https://github.com/pg2342-hub/complaint-signal-detector/actions/workflows/ci.yml/badge.svg)](https://github.com/pg2342-hub/complaint-signal-detector/actions/workflows/ci.yml)

Demo page: https://pg2342-hub.github.io/complaint-signal-detector/

Finds failure modes that are rising in a medical device's complaint stream, before they turn into a recall or a
correction. Built on public FDA adverse event reports (openFDA MAUDE) for one product, the Dexcom G7 CGM.

The question a quality team asks every week: *is any kind of complaint growing faster than the product's overall
complaint volume, and is it real?* This repo answers it three ways:

1. **Detect.** Count reports per failure mode by the month the event happened (not the month FDA received it, since
   manufacturers file in batches). Flag a mode when its share of the month's reports is well above its trailing
   six-month share: at least 30 reports, 1.5x expected, and a one-sided Poisson p-value at or below 0.001. Months that
   are still filling in are not scored.
2. **Backtest.** Replay the detector on only what FDA had *received* by each week before two public FDA actions on the
   G7, and record whether and how early it would have flagged the matching mode.
3. **Tag.** Most manufacturer reports carry a template allegation ("IT WAS REPORTED THAT ... OCCURRED") that keyword
   rules read well. Patient and clinician MedWatch reports are free text, and rules miss many of them. A Claude tagger
   reads those, with guardrails, and is scored against 76 hand-labeled reports with a release gate.

## Results (snapshot of November 23, 2026)

About 550,000 G7 reports with event dates from July 2024 to October 2026.

**Backtest: 1 of 4 public FDA actions flagged beforehand.**

| FDA action | Firm started | Result, using only reports FDA had received by each date |
|---|---|---|
| iOS app 2.7.0 correction, stale glucose values (Class II) | May 5, 2025 | Not flagged (strongest sign 1.1x) |
| Receiver speaker recall (Class I) | May 12, 2025 | Not flagged (strongest sign 1.3x) |
| App correction, missing "Sensor Failed" alert (Class I) | July 24, 2025 | **Flagged 14 days before**: June 2025 alert complaints at 2.0x their baseline share |
| iOS app correction, delayed values and alerts | April 14, 2026 | Not flagged (February 2026 reached 1.4x, under the 1.5x bar) |

Public reports arrive late, so most misses are expected. The point of the backtest is the method: run the same replay on a
manufacturer's own complaint feed, which sees the same complaints weeks earlier. A flag shows that a complaint type rose,
not what caused it.

**Tagging eval: 76 hand-labeled reports** (51 with the manufacturer's template, 25 free text), Claude Haiku 5.5.

| Tagger | Gate | Right | Safety reports filed under another mode | Sent to a person | Cost per 1,000 reports |
|---|---|---|---|---|---|
| Rules alone | no-go | 72 | 1 (a false low reading that ended in a coma, filed as adhesion) | 0 | free |
| Claude, raw answer | go | 76 | 0 | 0 | about $0.18 |
| Claude with guardrails | go | 74 | 0 | 2 | about $0.18 |

The free-text cases were found by searching for known wording, so the rules do better here than they would on new
wording. That is what the second Claude pass is for: it reads a sample of recent reports the rules cannot place. In
August 2026 it surfaced a new allegation wording, "pairing failure occurred", common since February 2026, which a person
then added to the signal-loss phrases (see `phrase_log` in the config).

Two fixes came out of the first runs and are in the history: the model's answer is now a structured JSON output with
room to think (in the first run, 15 of 76 answers could not be parsed, most likely cut off by a 300-token limit), and the template guardrail now reads only the allegation
sentence (it had let a "came off" later in a narrative override a correct "inaccurate readings" answer).

## The tagger and its guardrails

`src/csd/tagger.py` has three taggers scored side by side:

| tagger | what it does |
|---|---|
| rules | earliest known allegation phrase wins (the same phrases the openFDA counts use) |
| llm | Claude reads the narrative and returns a mode, a confidence and a short evidence quote |
| hybrid | the LLM answer, kept only if it passes the guardrails; otherwise the rules label or a person |

Guardrails on every LLM answer:

- the mode must be one of the product's modes (or `other`)
- the evidence quote must appear in the narrative word for word
- confidence below 0.6 goes to a person (`needs_review`)
- when the manufacturer's allegation sentence ("IT WAS REPORTED THAT ... OCCURRED") names a known mode, that mode
  wins and the disagreement is logged

The eval (`eval/`) uses [golive-gate](https://github.com/pg2342-hub/golive-gate). The gate: 90% of all cases correct,
80% of free-text cases correct, and zero cases where a safety mode (alert failure, inaccurate readings, skin reaction)
is hidden under a different label. Sending a case to `needs_review` is never a safety failure. Each run records cost
and latency per case.

## Run it

```bash
pip install -e ".[claude,dev]"
csd snapshot            # pull counts, backtest counts and eval narratives from openFDA into data/
python eval/build_cases.py
csd detect              # data/signals.json
csd backtest            # data/backtest_results.json
csd examples            # three example narratives per current signal
csd tag-eval            # Claude on the eval set (needs ANTHROPIC_API_KEY)
golive run eval/golive.yml --agent agent:hybrid_recorded --out reports/hybrid
python scripts/build_demo.py
```

Set `OPENFDA_API_KEY` for higher openFDA rate limits (optional). To point it at another product, copy
`config/dexcom_g7.yml` and change the search, the modes and their phrases, and the public events to backtest against.

## Limitations

- Public MAUDE data arrives weeks to months after the event. A manufacturer's own complaint feed sees the same
  reports much sooner, which is where this approach is meant to run.
- Rising counts are a signal to look, not proof of a defect. A flagged month and a later FDA action can coincide
  without being linked.
- Many recent reports have no narrative text, which can hide a rise but not create one.
- Failure modes come from fixed phrases, so a new kind of complaint shows up first in `csd unexplained`, not in the
  counts.
- Not affiliated with Dexcom or FDA. Uses only public data.

## License

MIT
