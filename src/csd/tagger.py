"""Tag one complaint narrative with a failure mode.

Three taggers, scored side by side in eval/:
- rules_tag:   earliest known allegation phrase wins (the same phrases the openFDA counts use)
- llm_tag:     Claude reads the narrative and picks a mode, with a short quote as evidence
- hybrid_tag:  the LLM tag, kept only if it passes the guardrails below; otherwise rules or a person

Guardrails on every LLM answer:
1. the mode must be one of the product's modes (or "other")
2. the evidence quote must appear in the narrative, word for word
3. confidence below the threshold goes to a person ("needs_review")
4. when the narrative carries the manufacturer's own allegation template and the rules found it,
   the rules label wins and the disagreement is logged (the template is the reporter's allegation)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .taxonomy import NEEDS_REVIEW, OTHER, Product

TEMPLATE = re.compile(r"\b(REPORTED THAT|REPORTED DETACHED|REPORTED BROKEN|COMPLAINT STATES)\b", re.I)


@dataclass
class Tag:
    mode: str
    method: str  # rules | llm | hybrid
    evidence: str = ""
    confidence: float | None = None
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "method": self.method,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "notes": self.notes,
            "cost_usd": round(self.cost_usd, 6),
            "latency_s": round(self.latency_s, 3),
        }


def has_template(text: str) -> bool:
    return bool(TEMPLATE.search(text))


def rules_tag(product: Product, text: str) -> Tag:
    best = None
    for mode in product.modes:
        hit = mode.first_match(text)
        if hit and (best is None or hit[0] < best[0]):
            best = (hit[0], hit[1], mode.id)
    if best is None:
        return Tag(OTHER, "rules", notes=["no known phrase"])
    return Tag(best[2], "rules", evidence=best[1])


# --- LLM tagger -------------------------------------------------------------------------------

PROMPT = """You label FDA medical device adverse event reports for a quality team.

Product: {product}

Pick the ONE failure mode that matches what the reporter says went wrong with the device. Use the reported
allegation, not the manufacturer's later investigation findings (for example, "IT WAS REPORTED THAT A PAIRING
ISSUE OCCURRED ... SIGNAL LOSS WAS FOUND" is a pairing complaint). If several problems are listed, pick the one
the report is mainly about. If the text is not a device complaint, or fits no mode, answer "other".

Modes:
{modes}
- other: not a device problem, or none of the above

Report narrative:
<narrative>
{text}
</narrative>

Answer with JSON only, no other text:
{{"mode": "<mode id>", "confidence": <0.0 to 1.0>, "evidence": "<a quote of at most 12 words copied exactly from the narrative>"}}"""

# USD per million tokens (input, output), first-party list prices.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class ClaudeTagger:
    def __init__(self, product: Product, model: str = "claude-haiku-5-5", client=None) -> None:
        if client is None:
            import anthropic  # optional dependency: pip install ".[claude]"

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.product = product

    def schema(self) -> dict:
        """Structured output: the API guarantees the answer parses and the mode is a known id."""
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": [*self.product.mode_ids, OTHER]},
                "confidence": {"type": "number"},
                "evidence": {"type": "string"},
            },
            "required": ["mode", "confidence", "evidence"],
            "additionalProperties": False,
        }

    def prompt(self, text: str) -> str:
        modes = "\n".join(f"- {m.id}: {m.description}" for m in self.product.modes)
        return PROMPT.format(product=self.product.name, modes=modes, text=text)

    def __call__(self, text: str) -> Tag:
        start = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            # room for the model's thinking plus the short JSON answer; 300 was cut off mid-thought
            max_tokens=2000,
            messages=[{"role": "user", "content": self.prompt(text)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": self.schema()}},
        )
        latency = time.perf_counter() - start
        price = PRICES.get(getattr(response, "model", self.model)) or PRICES.get(self.model, (0, 0))
        cost = (response.usage.input_tokens * price[0] + response.usage.output_tokens * price[1]) / 1e6
        raw = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "text") == "text")
        tag = parse_llm_answer(raw)
        stop = getattr(response, "stop_reason", None)
        if tag.mode == NEEDS_REVIEW and stop not in (None, "end_turn"):
            tag.notes.append(f"stop_reason {stop}")
        tag.cost_usd, tag.latency_s = cost, latency
        return tag


def parse_llm_answer(raw: str) -> Tag:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return Tag(NEEDS_REVIEW, "llm", notes=["answer was not JSON"])
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return Tag(NEEDS_REVIEW, "llm", notes=["answer was not valid JSON"])
    try:
        conf = float(data.get("confidence"))
    except (TypeError, ValueError):
        conf = None
    return Tag(
        str(data.get("mode", "")).strip(), "llm", evidence=str(data.get("evidence", "")).strip(), confidence=conf
    )


# --- guardrails -------------------------------------------------------------------------------


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def guard(product: Product, text: str, llm: Tag, min_confidence: float = 0.6) -> Tag:
    """Apply the guardrails to an LLM tag and return the final (hybrid) tag."""
    allowed = set(product.mode_ids) | {OTHER}
    out = Tag(llm.mode, "hybrid", llm.evidence, llm.confidence, list(llm.notes), llm.cost_usd, llm.latency_s)
    rules = rules_tag(product, text)

    if llm.mode == NEEDS_REVIEW:
        out.mode = NEEDS_REVIEW
    elif llm.mode not in allowed:
        out.mode, out.notes = NEEDS_REVIEW, out.notes + [f"unknown mode '{llm.mode}'"]
    elif not llm.evidence or _norm(llm.evidence) not in _norm(text):
        out.mode, out.notes = NEEDS_REVIEW, out.notes + ["evidence quote not found in narrative"]
    elif llm.confidence is None or llm.confidence < min_confidence:
        out.mode, out.notes = NEEDS_REVIEW, out.notes + [f"confidence {llm.confidence} below {min_confidence}"]

    if has_template(text) and rules.mode != OTHER and out.mode != rules.mode:
        out.notes.append(f"template allegation says {rules.mode}; LLM said {llm.mode}")
        out.mode, out.evidence = rules.mode, rules.evidence
    return out
