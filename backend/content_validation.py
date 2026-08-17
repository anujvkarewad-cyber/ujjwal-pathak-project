"""Server-side revalidation of mentor edits — mirrors the pipeline's content
validation invariants (docs/integration-design.md §5.3). Mentor edits can
never bypass the same gates the pipeline enforces."""
import re

BLOCKED_PATTERNS = [
    re.compile(r"as\s+an\s+ai\b", re.I),
    re.compile(r"i\s+cannot\b", re.I),
    re.compile(r"as\s+a\s+language\s+model\b", re.I),
    re.compile(r"\(\s*insert\s+[^)]*\)", re.I),
    re.compile(r"lorem\s+ipsum", re.I),
    re.compile(r"\[(placeholder|todo|tbd|xxx)\]", re.I),
]

SOURCE_KINDS = ("module", "RTP", "MTP", "PYQ")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def validate_question(q: dict) -> tuple[list, list]:
    """Returns (errors, warnings) for a question document."""
    errors: list = []
    warnings: list = []

    options = q.get("options") or []
    if len(options) != 4:
        errors.append(f"expected 4 options, got {len(options)}")
    texts = [_norm(o.get("text", "")) for o in options]
    if any(not t for t in texts):
        errors.append("at least one option is empty")
    if len(set(texts)) != len(texts):
        errors.append("options are not pairwise distinct")
    ids = [str(o.get("id", "")) for o in options]
    if len(set(ids)) != len(ids):
        errors.append("option ids are not unique")
    if str(q.get("correctOptionId")) not in ids:
        errors.append(f'correctOptionId "{q.get("correctOptionId")}" does not match any option id')
    prompt_norm = _norm(q.get("prompt"))
    if prompt_norm in texts:
        errors.append("an option duplicates the prompt verbatim")

    if len((q.get("prompt") or "").strip()) < 10:
        errors.append("prompt too short")
    if len((q.get("explanation") or "").strip()) < 10:
        errors.append("explanation too short")
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(f"{q.get('prompt')} {q.get('explanation')} {' '.join(texts)}"):
            errors.append(f"generation artifact detected: {pattern.pattern}")

    if not q.get("icaiSourceRefs"):
        errors.append("missing ICAI module source reference(s)")
    if not q.get("calibrationRefs"):
        errors.append("missing RTP/MTP/PYQ calibration reference(s)")

    if q.get("questionType") == "scenario_mcq":
        scenario = q.get("scenario") or {}
        if not scenario.get("scenarioId"):
            errors.append("scenario_mcq missing scenario linkage")
        elif scenario.get("blockTotal") != 4:
            errors.append(f'scenario blockTotal must be 4, got {scenario.get("blockTotal")}')
        elif not (isinstance(scenario.get("seq"), int) and 1 <= scenario["seq"] <= 4):
            errors.append(f'scenario seq must be 1-4, got {scenario.get("seq")}')
    elif q.get("questionType") == "mcq" and q.get("scenario") is not None:
        errors.append("plain mcq must have scenario: null")

    if not q.get("conceptTags"):
        errors.append("at least one conceptTag is required")
    if q.get("attemptSpecificRisk") and not q.get("attemptSpecificRiskConfirmed"):
        warnings.append("attempt-specific legal/tax content flagged — mentor confirmation required before publish")

    return errors, warnings


def validate_scenario(s: dict) -> tuple[list, list]:
    errors: list = []
    warnings: list = []
    question_ids = s.get("questionIds") or []
    if len(question_ids) != 4:
        errors.append(f"scenario must link exactly 4 questions, got {len(question_ids)}")
    if len(set(question_ids)) != len(question_ids):
        errors.append("scenario questionIds are not unique")
    if len((s.get("passage") or "").strip()) < 40:
        errors.append("scenario passage too short")
    if not s.get("icaiSourceRefs"):
        errors.append("scenario missing ICAI module source reference(s)")
    if not s.get("calibrationRefs"):
        errors.append("scenario missing RTP/MTP/PYQ calibration reference(s)")
    if s.get("attemptSpecificRisk") and not s.get("attemptSpecificRiskConfirmed"):
        warnings.append("attempt-specific legal/tax content flagged — mentor confirmation required before publish")
    return errors, warnings


def chapter_gate(chapter_id: str, questions: list, scenarios: list, plain_target=30, scenarios_target=5, per_scenario=4) -> dict:
    """Chapter publish gate (§7.3). Returns {errors, warnings, coverage}."""
    errors: list = []
    warnings: list = []
    plain = [q for q in questions if q.get("questionType") == "mcq"]
    scenario_qs = [q for q in questions if q.get("questionType") == "scenario_mcq"]
    coverage = {
        "plainApproved": len(plain),
        "plainTarget": plain_target,
        "scenariosApproved": len(scenarios),
        "scenariosTarget": scenarios_target,
        "scenarioMcqsApproved": len(scenario_qs),
        "scenarioMcqsTarget": scenarios_target * per_scenario,
    }
    # Minimums, not exact counts: extra approved items must not lock the gate.
    if len(plain) < plain_target:
        errors.append(f"{plain_target} plain MCQs not all approved (have {len(plain)})")
    if len(scenarios) < scenarios_target:
        errors.append(f"{scenarios_target} scenarios not all approved (have {len(scenarios)})")
    if len(scenario_qs) < scenarios_target * per_scenario:
        errors.append(f"all {scenarios_target * per_scenario} scenario MCQs not approved (have {len(scenario_qs)})")

    linked_ids = {qid for s in scenarios for qid in (s.get("questionIds") or [])}
    for q in scenario_qs:
        sc = q.get("scenario") or {}
        if q["id"] not in linked_ids:
            errors.append(f"{q['id']}: scenario_mcq not linked from any scenario block")
        elif sc.get("scenarioId") not in {s.get("scenarioId") for s in scenarios}:
            errors.append(f"{q['id']}: links to unknown scenario")

    for q in questions:
        q_errors, q_warnings = validate_question(q)
        for e in q_errors:
            errors.append(f"{q.get('id', '?')}: {e}")
        for w in q_warnings:
            if not q.get("warningsAcknowledged") and not q.get("attemptSpecificRiskConfirmed"):
                warnings.append(f"{q.get('id', '?')}: {w}")
    for s in scenarios:
        s_errors, s_warnings = validate_scenario(s)
        for e in s_errors:
            errors.append(f"{s.get('scenarioId', '?')}: {e}")
        for w in s_warnings:
            warnings.append(f"{s.get('scenarioId', '?')}: {w}")
    return {"errors": errors, "warnings": warnings, "coverage": coverage}
