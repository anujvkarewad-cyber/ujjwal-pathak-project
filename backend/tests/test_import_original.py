"""Tests for backend/import_original.py — the generated-content importer.

Covers the source→backend field mapping (answerIndex 0-3 → correctOptionId A-D,
Easy/Medium/Hard → easy/moderate/hard, plain[30] + scenarios[5].linkedMcqs[4]),
the demo-data purge, and re-import behaviour.
"""
import asyncio
import json

import pytest

import import_original as imp
import seed_demo
from db import (
    ANALYTICS_CONSENTS,
    ANALYTICS_SUMMARIES,
    CONTENT_CHAPTERS,
    CONTENT_QUESTIONS,
    CONTENT_SCENARIOS,
    get_db,
)


def _mcq(i, kind="plain"):
    return {
        "question": f"Which treatment of item {i} ({kind}) is correct as per the applicable standard?",
        "options": [f"Option {letter} for item {i} ({kind})" for letter in "ABCD"],
        "answerIndex": i % 4,
        "explanation": f"Explanation {i}: the standard prescribes this treatment for the {kind} case.",
        "difficulty": ["Easy", "Medium", "Hard"][i % 3],
        "conceptTags": ["accounting-standards"],
    }


def _chapter_payload(chapter_id="advanced-accounting-1"):
    return {
        "chapterId": chapter_id,
        "generatedAt": "2026-08-01T10:00:00Z",
        "plain": [_mcq(i) for i in range(1, 31)],
        "scenarios": [
            {
                "passage": (
                    f"Case scenario {s}: a listed company applies the chapter's requirements to a "
                    "transaction spanning two reporting periods, with the figures given below."
                ),
                "linkedMcqs": [_mcq(s * 10 + k, "scenario") for k in range(1, 5)],
            }
            for s in range(1, 6)
        ],
    }


@pytest.fixture()
def generated_dir(tmp_path):
    root = tmp_path / "content-pipeline" / "generated" / "accounts"
    root.mkdir(parents=True)
    (root / "advanced-accounting-1.json").write_text(json.dumps(_chapter_payload()), encoding="utf-8")
    (root / "advanced-accounting-2.json").write_text(
        json.dumps(_chapter_payload("advanced-accounting-2")), encoding="utf-8"
    )
    return tmp_path / "content-pipeline" / "generated"


def test_difficulty_and_answer_mapping():
    assert imp.normalize_difficulty("Easy") == "easy"
    assert imp.normalize_difficulty("Medium") == "moderate"
    assert imp.normalize_difficulty("Hard") == "hard"

    options = imp.normalize_options(["one", "two", "three", "four"])
    assert [o["id"] for o in options] == ["A", "B", "C", "D"]
    for index, expected in enumerate(["A", "B", "C", "D"]):
        assert imp.resolve_correct_option_id({"answerIndex": index}, options) == expected
    # letter / text answers are accepted too
    assert imp.resolve_correct_option_id({"correctOptionId": "C"}, options) == "C"
    assert imp.resolve_correct_option_id({"answer": "three"}, options) == "C"


def test_convert_file_shapes_documents(generated_dir):
    path = next(generated_dir.rglob("advanced-accounting-1.json"))
    result = imp.convert_file(path, imp.load_catalog())

    questions = result["questions"]
    scenarios = result["scenarios"]
    plain = [q for q in questions if q["questionType"] == "mcq"]
    scenario_mcqs = [q for q in questions if q["questionType"] == "scenario_mcq"]

    assert len(plain) == 30
    assert len(scenarios) == 5
    assert len(scenario_mcqs) == 20

    q = plain[0]
    assert q["id"].startswith("adp_q_advanced-accounting-1")
    assert q["status"] == "needs_review"
    assert q["statusHistory"][-1]["to"] == "needs_review"
    assert [o["id"] for o in q["options"]] == ["A", "B", "C", "D"]
    assert q["correctOptionId"] in ("A", "B", "C", "D")
    assert q["difficulty"] in ("easy", "moderate", "hard")
    assert q["icaiSourceRefs"] and q["calibrationRefs"]
    assert set(q["generationMeta"]) >= {"model", "promptVersion", "generatedAt"}
    assert q["scenario"] is None
    # catalog enrichment
    assert q["subject"] and q["chapterTitle"] and q["chapterNumber"] == 1

    linked = scenario_mcqs[0]
    assert linked["scenario"]["scenarioId"] == scenarios[0]["scenarioId"]
    assert linked["scenario"]["blockTotal"] == 4
    assert linked["scenario"]["seq"] == 1
    assert scenarios[0]["questionIds"] == [q["id"] for q in scenario_mcqs[:4]]
    assert scenarios[0]["scenarioId"].startswith("adp_s_")

    # every imported question passes the backend's own validation
    assert [e for q in questions for e in q["validation"]["errors"]] == []
    assert len({q["id"] for q in questions}) == 50


def test_convert_file_remints_colliding_scenario_ids(tmp_path):
    """Real generated files reuse plain IDs for scenario MCQs (…_011)."""
    payload = {
        "chapterId": "advanced-accounting-1",
        "plain": [
            {
                "id": "adp_q_advanced-accounting-1_011",
                "prompt": "Plain question eleven about SMC classification under the rules?",
                "options": ["A text here", "B text here", "C text here", "D text here"],
                "answerIndex": 0,
                "explanation": "Plain eleven explanation covering the applicable rule in enough detail.",
                "difficulty": "Easy",
                "conceptTags": ["smc"],
            }
        ],
        "scenarios": [
            {
                "passage": "A listed company borrows fifty four crore for ten days during the year under review.",
                "linkedMcqs": [
                    {
                        "id": "adp_q_advanced-accounting-1_011",
                        "prompt": "Scenario question that reused the plain id — what is the classification?",
                        "options": ["SMC", "Non-SMC", "Level IV", "Exempt"],
                        "answerIndex": 1,
                        "explanation": "Borrowings exceeded the SMC ceiling even for a few days, so Non-SMC applies.",
                        "difficulty": "Medium",
                        "conceptTags": ["smc"],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "advanced-accounting-1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = imp.convert_file(path, {})
    ids = [q["id"] for q in result["questions"]]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert "adp_q_advanced-accounting-1_011" in ids


def test_run_import_writes_documents_and_purges_demo(generated_dir):
    async def scenario():
        await seed_demo.seed()
        db = get_db()
        assert await db[CONTENT_QUESTIONS].count_documents({"chapterId": "ch-acc-01"}) == 50

        report = await imp.run_import(str(generated_dir), quiet=True)
        assert report["ok"] is True
        assert report["stats"]["chapters"] == 2
        assert report["stats"]["questions_inserted"] == 100
        assert report["stats"]["scenarios_inserted"] == 10

        # demo records are gone
        assert await db[CONTENT_QUESTIONS].count_documents({"chapterId": "ch-acc-01"}) == 0
        assert await db[CONTENT_QUESTIONS].count_documents({"generationMeta.model": "demo-seed"}) == 0
        assert await db[CONTENT_SCENARIOS].count_documents({"chapterId": "ch-law-03"}) == 0
        assert await db[CONTENT_CHAPTERS].count_documents({"chapterId": {"$in": ["ch-acc-01", "ch-law-03"]}}) == 0
        assert await db[ANALYTICS_CONSENTS].count_documents({"studentId": {"$in": seed_demo.DEMO_STUDENTS}}) == 0
        assert await db[ANALYTICS_SUMMARIES].count_documents({"studentId": {"$in": seed_demo.DEMO_STUDENTS}}) == 0

        # real content is there
        assert await db[CONTENT_QUESTIONS].count_documents({"chapterId": "advanced-accounting-1"}) == 50
        assert await db[CONTENT_SCENARIOS].count_documents({"chapterId": "advanced-accounting-1"}) == 5
        chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": "advanced-accounting-1"})
        assert chapter["imported"] == {
            **chapter["imported"],
            "plain": 30,
            "scenarios": 5,
            "scenarioMcqs": 20,
        }

        # re-import is idempotent and leaves mentor decisions alone
        await db[CONTENT_QUESTIONS].update_one(
            {"id": "adp_q_advanced-accounting-1_001"}, {"$set": {"status": "approved"}}
        )
        await db[CONTENT_CHAPTERS].update_one(
            {"chapterId": "advanced-accounting-1"},
            {"$set": {"status": "published", "releaseCandidate": {"revision": 7}}},
        )
        again = await imp.run_import(str(generated_dir), quiet=True)
        assert again["stats"]["questions_inserted"] == 0
        assert again["stats"]["questions_unchanged"] == 99
        assert again["stats"]["questions_protected"] == 1
        approved = await db[CONTENT_QUESTIONS].find_one({"id": "adp_q_advanced-accounting-1_001"})
        assert approved["status"] == "approved"
        preserved_chapter = await db[CONTENT_CHAPTERS].find_one({"chapterId": "advanced-accounting-1"})
        assert preserved_chapter["status"] == "published"
        assert preserved_chapter["releaseCandidate"] == {"revision": 7}

    asyncio.run(scenario())


def test_dry_run_writes_nothing(generated_dir):
    async def scenario():
        report = await imp.run_import(str(generated_dir), dry_run=True, quiet=True)
        assert report["dryRun"] is True
        assert await get_db()[CONTENT_QUESTIONS].count_documents({}) == 0

    asyncio.run(scenario())


def test_detect_generated_dir_prefers_explicit_path(generated_dir, tmp_path):
    assert imp.detect_generated_dir(str(generated_dir)) == generated_dir
    assert imp.detect_generated_dir(str(tmp_path / "nope")) is None
