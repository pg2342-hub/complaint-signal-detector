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

## Results

See the [demo page](https://pg2342-hub.github.io/complaint-signal-detector/) for the current numbers, the backtest
timeline per event, and the full eval report. They are regenerated from openFDA by the Snapshot workflow.

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
- when the manufacturer's template allegation is present and the rules found it, the rules label wins and the
  disagreement is logged

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
