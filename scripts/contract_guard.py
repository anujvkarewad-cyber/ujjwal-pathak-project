#!/usr/bin/env python3
"""Static contract guard — runs before every deploy (wired into scripts/deploy.sh).

These checks catch the exact class of defect that keeps reaching production:
a change that is correct in isolation but breaks a contract somebody else
depends on. They need no database and finish in about a second.

Rules
-----
RULE-1  A STUDENT-FACING read must never answer 5xx for a business rule.
        A missing / withheld / unclassified thing is answered with 200 and an
        empty or "found": false payload (FIX 3 in PERMANENT_FIX_PLAN.md).
        5xx is only for a real infrastructure failure (Mongo down, timeout, a
        service that is not configured). Mentor-facing writes keep their 503 -
        "nothing was saved" must stay loud there.

RULE-2  A tuple must not be indexed past its length.
        The day-strip bug (key[2] on a 2-tuple) turned every
        /api/ai/target-plan-days call into a 500 for students.

RULE-3  A shared, audience-targeted row must be filtered for the reader.
        A shared announcement leaked into every batch before this check
        existed.

RULE-4  No breakpoint()/pdb in backend code.

Exit code 0 = clean. Non-zero = do not deploy.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
ROUTERS = BACKEND / "routers"

failures: list[str] = []

# Dependencies that mean "this route serves a student app".
STUDENT_DEPS = {"dashboard_student", "workspace_student", "student_auth",
                "require_student", "student_principal"}

# Wording that proves the 5xx is an infrastructure/config failure.
INFRA_WORDS = (
    "not configured", "not set up", "is busy", "try again", "please try again",
    "bridge", "timeout", "no response", "connection refused", "connection error",
    "service is down", "temporarily unavailable",
)


def fail(rule: str, path: pathlib.Path, line: int, message: str) -> None:
    try:
        rel = path.relative_to(BACKEND)
    except ValueError:
        rel = path
    failures.append(f"{rule}  {rel}:{line}: {message}")


def _route_decorators(node) -> list[str]:
    """HTTP methods this function is registered for."""
    out = []
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in {"get", "post", "put",
                                                                "patch", "delete"}:
            out.append(target.attr)
    return out


def _dep_name(node) -> str:
    """The dependency function name of a Depends(...) call, if any.

    Depends(dashboard_student) -> "dashboard_student"
    """
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    if fname == "Depends":
        # the dependency is the first positional argument
        if node.args:
            inner = node.args[0]
            if isinstance(inner, ast.Name):
                return inner.id
            if isinstance(inner, ast.Attribute):
                return inner.attr
        return ""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_student_facing(node) -> bool:
    """True when the route authenticates a student app client.

    Detected as: Depends(dashboard_student) / Depends(workspace_student) /
    a direct call of one of those guards inside the body.
    """
    args = node.args
    # Python's AST keeps positional defaults in `arguments.defaults`, aligned to
    # the LAST n positional args (not on the arg node itself).
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults = list(args.defaults)
    pairs: list[tuple] = []
    if defaults:
        offset = len(positional) - len(defaults)
        for i, default in enumerate(defaults):
            pairs.append((positional[offset + i], default))
    for arg, default in zip(list(args.kwonlyargs), list(args.kw_defaults)):
        pairs.append((arg, default))
    for _arg, default in pairs:
        if default is None:
            continue
        # Depends(dashboard_student)  — positional
        if _dep_name(default) in STUDENT_DEPS:
            return True
        # Depends(dependency=dashboard_student)
        if isinstance(default, ast.Call):
            for kw in default.keywords:
                if kw.arg == "dependency" and _dep_name(kw.value) in STUDENT_DEPS:
                    return True
        if isinstance(default, ast.Name) and default.id in STUDENT_DEPS:
            return True
    # Direct call of a student guard inside the body.
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _dep_name(sub) in STUDENT_DEPS:
            return True
    return False


def _status_code(call) -> int | None:
    """The status code of an HTTPException(...)/deny(...) call, if literal."""
    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(
        call.func, "id", "")
    if name == "deny":
        if call.args and isinstance(call.args[0], ast.Constant) and \
                isinstance(call.args[0].value, int):
            return call.args[0].value
        return None
    if name != "HTTPException":
        return None
    for kw in call.keywords:
        if kw.arg == "status_code" and isinstance(kw.value, ast.Constant) and \
                isinstance(kw.value.value, int):
            return kw.value.value
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant) and \
            isinstance(call.args[1].value, int):
        return call.args[1].value
    return None


def _detail_text(call) -> str:
    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(
        call.func, "id", "")
    parts = []
    if name == "deny" and len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        parts.append(str(call.args[1].value))
    for kw in call.keywords:
        if kw.arg in {"detail", "message"} and isinstance(kw.value, ast.Constant):
            parts.append(str(kw.value.value))
    return " ".join(parts).lower()


# ------------------------------------------------------------------ RULE-1
def rule_no_business_5xx() -> None:
    for path in sorted(ROUTERS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _route_decorators(node):
                continue
            if not _is_student_facing(node):
                continue  # mentor-facing: 503 stays loud on purpose
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                code = _status_code(sub)
                if code is None or code < 500:
                    continue
                detail = _detail_text(sub)
                if any(w in detail for w in INFRA_WORDS):
                    continue  # real infrastructure/config failure
                fail("RULE-1", path, sub.lineno,
                     f"student-facing route answers {code} for a business rule "
                     f"(answer 200 + empty/reason instead)")


# ------------------------------------------------------------------ RULE-2
def rule_no_tuple_overread() -> None:
    for path in sorted(ROUTERS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            lengths: dict[str, int] = {}
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                        lengths[node.targets[0].id] = len(node.value.elts)
            if not lengths:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                        and node.value.id in lengths
                        and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, int)):
                    idx = node.slice.value
                    if idx >= lengths[node.value.id]:
                        fail("RULE-2", path, node.lineno,
                             f"{node.value.id} is a {lengths[node.value.id]}-tuple but is "
                             f"indexed with [{idx}]")


# ------------------------------------------------------------------ RULE-3
def rule_shared_reads_are_filtered() -> None:
    """A shared, audience-targeted row must be filtered for the reader."""
    checks = (
        ("routers/student_dashboard.py", "_announcements_for_student", "announcements"),
        ("routers/student_dashboard.py", "_notes_for_student", "notes"),
    )
    for rel, helper, subject in checks:
        path = BACKEND / rel
        src = path.read_text(encoding="utf-8")
        if f"def {helper}" not in src:
            fail("RULE-3", path, 1, f"missing the {helper}() audience filter for {subject}")
        elif src.count(helper) < 2:
            fail("RULE-3", path, 1,
                 f"{helper}() is defined but never used - the shared {subject} "
                 f"read is unfiltered")


# ------------------------------------------------------------------ RULE-4
def rule_no_debugger() -> None:
    for path in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if re.match(r"^(breakpoint\(\)|pdb\.set_trace)", stripped):
                fail("RULE-4", path, i, "debugger left in the code")


def main() -> int:
    rule_no_business_5xx()
    rule_no_tuple_overread()
    rule_shared_reads_are_filtered()
    rule_no_debugger()

    if failures:
        print(f"\n{len(failures)} contract violation(s) — DO NOT DEPLOY:\n")
        for f in failures:
            print("  ✗ " + f)
        return 1
    print("✓ contract guard clean (rules 1-4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
