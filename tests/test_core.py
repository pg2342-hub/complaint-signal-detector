import io
import json
import urllib.error
from pathlib import Path

import pytest

from csd import backtest as bt
from csd.detect import poisson_tail, scan
from csd.openfda import OpenFDA, narrative
from csd.tagger import Tag, guard, parse_llm_answer, rules_tag
from csd.taxonomy import NEEDS_REVIEW, OTHER, load_product

PRODUCT = load_product(Path(__file__).parents[1] / "config" / "dexcom_g7.yml")


@pytest.mark.parametrize(
    "text,mode",
    [
        ("IT WAS REPORTED THAT A PAIRING ISSUE OCCURRED. ... SIGNAL LOSS OVER AN HOUR WAS FOUND.", "signal_loss"),
        (
            "IT WAS REPORTED THAT AN ALERT/NOTIFICATION SETTINGS ISSUE OCCURRED. THE SPEAKER WAS TESTED.",
            "alert_failure",
        ),
        ("IT WAS REPORTED THAT A SKIN REACTION OCCURRED. THE ADHESIVE OF THE OVERLAY PATCH PEELED.", "skin_reaction"),
        ("IT WAS REPORTED DETACHED OR MISSING SENSOR WIRE OCCURRED.", "sensor_wire_or_needle"),
        (
            "NO READINGS/ SENSOR ERROR/ BRIEF SENSOR ISSUE OCCURRED. HOWEVER, SIGNAL LOSS OCCURRED",
            "early_sensor_failure",
        ),
        ("2 DEXCOM SENSORS FELL OFF WITHIN 24 HOURS", "adhesion"),
        ("DON ABBEY ORG Q1 2025 ALL HANDS MEETING.", OTHER),
    ],
)
def test_rules_earliest_allegation_wins(text, mode):
    assert rules_tag(PRODUCT, text).mode == mode


def test_openfda_query_quotes_every_phrase():
    q = PRODUCT.mode("signal_loss").openfda_query()
    assert q.startswith("mdr_text.text:(") and '"pairing issue occurred"' in q


TEXT = "MY SENSOR KEPT LOSING CONNECTION TO MY PHONE FOR HOURS AND MISSED A LOW."


def test_guard_keeps_a_good_answer():
    out = guard(PRODUCT, TEXT, Tag("signal_loss", "llm", "LOSING CONNECTION TO MY PHONE", 0.9))
    assert out.mode == "signal_loss" and out.method == "hybrid"


@pytest.mark.parametrize(
    "tag,why",
    [
        (Tag("bluetooth", "llm", "LOSING CONNECTION", 0.9), "unknown mode"),
        (Tag("signal_loss", "llm", "the sensor exploded", 0.9), "evidence"),
        (Tag("signal_loss", "llm", "LOSING CONNECTION", 0.3), "confidence"),
    ],
)
def test_guard_sends_bad_answers_to_review(tag, why):
    out = guard(PRODUCT, TEXT, tag)
    assert out.mode == NEEDS_REVIEW and any(why in n for n in out.notes)


def test_guard_template_allegation_overrides_model():
    text = "IT WAS REPORTED THAT A PAIRING ISSUE OCCURRED. SIGNAL LOSS OVER ONE HOUR WAS FOUND."
    out = guard(PRODUCT, text, Tag("early_sensor_failure", "llm", "SIGNAL LOSS OVER ONE HOUR", 0.95))
    assert out.mode == "signal_loss" and "template allegation" in out.notes[-1]


def test_parse_llm_answer():
    t = parse_llm_answer('Sure: {"mode": "adhesion", "confidence": 0.8, "evidence": "fell off"}')
    assert (t.mode, t.confidence, t.evidence) == ("adhesion", 0.8, "fell off")
    assert parse_llm_answer("no json here").mode == NEEDS_REVIEW


class FakeClient:
    class messages:  # noqa: N801
        @staticmethod
        def create(**kw):
            class U:
                input_tokens, output_tokens = 1000, 50

            class B:
                text = '{"mode": "signal_loss", "confidence": 0.9, "evidence": "LOSING CONNECTION"}'

            class R:
                model, usage, content = "claude-haiku-5-5", U, [B]

            return R


def test_claude_tagger_reports_cost():
    from csd.tagger import ClaudeTagger

    tag = ClaudeTagger(PRODUCT, client=FakeClient)(TEXT)
    assert tag.mode == "signal_loss" and tag.cost_usd == pytest.approx((1000 * 0.10 + 50 * 0.50) / 1e6)


def test_poisson_tail():
    assert poisson_tail(0, 5) == 1.0
    assert poisson_tail(10, 10) == pytest.approx(0.5421, abs=1e-3)
    assert poisson_tail(200, 100) < 1e-15


def _series(spike_month_value):
    months = [f"2025-{m:02d}" for m in range(1, 10)]
    totals = {m: 10000 for m in months}
    counts = {m: 400 for m in months}
    counts["2025-08"] = spike_month_value
    return {"alert_failure": counts}, totals


def test_scan_flags_a_share_spike_and_ignores_noise():
    series, totals = _series(800)
    flagged = [s for s in scan(series, totals) if s.flagged]
    assert [s.month for s in flagged] == ["2025-08"]
    series, totals = _series(430)
    assert not any(s.flagged for s in scan(series, totals))


def test_scan_waits_for_incomplete_month():
    series, totals = _series(800)
    totals["2025-08"] = 3000  # only 30% of the usual reports have arrived
    series["alert_failure"]["2025-08"] = 240
    assert not any(s.flagged for s in scan(series, totals))


def test_backtest_lead_time():
    series, totals = _series(800)
    early = {"alert_failure": {k: v for k, v in series["alert_failure"].items() if k < "2025-08"}}
    ev = {
        "id": "e",
        "title": "t",
        "date": "2025-10-01",
        "mode": "alert_failure",
        "source": "s",
        "detail": "d",
        "points": [
            {
                "as_of": "2025-08-15",
                "with_narrative": {k: v for k, v in totals.items() if k < "2025-08"},
                "mode": early["alert_failure"],
            },
            {"as_of": "2025-09-10", "with_narrative": totals, "mode": series["alert_failure"]},
        ],
    }
    r = bt.run_event(ev)
    assert r["caught_before_event"] and r["first_flag_as_of"] == "2025-09-10" and r["lead_days"] == 21


def test_openfda_client_404_is_empty_and_url_is_encoded():
    seen = []

    def opener(url, timeout):
        seen.append(url)
        if "nothing" in url:
            raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
        return io.BytesIO(
            json.dumps({"results": [{"time": "20250102", "count": 3}, {"time": "20250120", "count": 4}]}).encode()
        )

    api = OpenFDA(api_key="", pause_s=0, opener=opener)
    assert api.count_by_month('device.brand_name:"dexcom g7"') == {"2025-01": 7}
    assert api.get("nothing") == {"results": []}
    assert 'brand_name:"dexcom+g7"' in seen[0]


def test_narrative_joins_description_only():
    rec = {
        "mdr_text": [
            {"text_type_code": "Additional Manufacturer Narrative", "text": "(B)(4)."},
            {"text_type_code": "Description of Event or Problem", "text": "SIGNAL  LOSS"},
        ]
    }
    assert narrative(rec) == "SIGNAL LOSS"
