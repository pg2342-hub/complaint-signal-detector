"""Build eval/cases.json from the hand labels (eval/labels.csv) and the narratives pulled from openFDA."""

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

from csd.tagger import has_template  # noqa: E402
from csd.taxonomy import load_product  # noqa: E402


def build() -> dict:
    product = load_product(HERE.parent / "config" / "dexcom_g7.yml")
    safety = {m.id for m in product.modes if m.safety}
    reports = json.loads((HERE.parent / "data" / "eval_reports.json").read_text())
    cases = []
    for row in csv.DictReader((HERE / "labels.csv").open()):
        rec = reports.get(row["report_number"])
        if rec is None:
            continue
        text = rec["narrative"]
        cases.append(
            {
                "id": row["report_number"],
                "group": "template" if has_template(text) else "free_text",
                "title": text[:80],
                "input": {"report_number": row["report_number"], "narrative": text},
                "expected": {"mode": row["label"], "safety": row["label"] in safety},
            }
        )
    return {"cases": cases}


if __name__ == "__main__":
    doc = build()
    (HERE / "cases.json").write_text(json.dumps(doc, indent=1))
    groups = {}
    for c in doc["cases"]:
        groups[c["group"]] = groups.get(c["group"], 0) + 1
    print(f"wrote {len(doc['cases'])} cases {groups}")
