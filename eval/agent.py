"""The taggers under test, as golive-gate agents. Each takes a case input and returns a tag dict.

rules_agent       the phrase rules alone
llm_recorded      the Claude tagger's raw answers, recorded by `csd tag-eval` (data/llm_eval_tags.json)
hybrid_recorded   the same answers after the guardrails
llm_live / hybrid_live  call Claude now (needs ANTHROPIC_API_KEY); cost is recorded per case
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

from golive_gate import Response  # noqa: E402

from csd.tagger import ClaudeTagger, guard, rules_tag  # noqa: E402
from csd.taxonomy import load_product  # noqa: E402

PRODUCT = load_product(HERE.parent / "config" / "dexcom_g7.yml")
RECORDED = HERE.parent / "data" / "llm_eval_tags.json"


def rules_agent(case_input):
    return rules_tag(PRODUCT, case_input["narrative"]).as_dict()


def _recorded(kind):
    def agent(case_input):
        tags = json.loads(RECORDED.read_text())["tags"]
        tag = tags[case_input["report_number"]][kind]
        return Response(tag, cost_usd=tag.get("cost_usd", 0.0))

    agent.__name__ = f"{kind}_recorded"
    return agent


llm_recorded = _recorded("llm")
hybrid_recorded = _recorded("hybrid")

_tagger = None


def _live(case_input):
    global _tagger
    if _tagger is None:
        _tagger = ClaudeTagger(PRODUCT)
    return _tagger(case_input["narrative"])


def llm_live(case_input):
    tag = _live(case_input)
    return Response(tag.as_dict(), cost_usd=tag.cost_usd)


def hybrid_live(case_input):
    raw = _live(case_input)
    tag = guard(PRODUCT, case_input["narrative"], raw)
    return Response(tag.as_dict(), cost_usd=tag.cost_usd)
