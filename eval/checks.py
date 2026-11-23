from golive_gate import NA, CheckSet

checks = CheckSet()


@checks.check("mode", text="The tag is the labeled failure mode.")
def mode(case, out):
    if out["mode"] == case.expected["mode"]:
        return True
    return False, f"tagged {out['mode']}, label is {case.expected['mode']}"


@checks.check(
    "safety_not_hidden",
    text="A report labeled with a safety mode (alerts, inaccurate readings, skin reactions) is tagged with that mode or sent to a person, never silently filed under another mode.",
    critical=True,
)
def safety_not_hidden(case, out):
    if not case.expected["safety"]:
        return NA
    if out["mode"] in (case.expected["mode"], "needs_review"):
        return True
    return False, f"safety report filed as {out['mode']}"
