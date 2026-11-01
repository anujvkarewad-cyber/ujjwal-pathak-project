"""Dev/demo seed for the mentor analytics collections (MONGO_URL=memory:// only).

Loads the same shapes the student app syncs via /api/progress-sync and
/api/test-history/sync, so the mentor dashboard Analytics pages show real
results in the sandbox:

  - analytics_consents      — sharing ON/OFF per student
  - analytics_summaries     — consented per-chapter MCQ mastery summaries
  - analytics_trends        — weekly mastery snapshots (improving/declining)
  - analytics_test_history  — mentor test attempts (MCQ + paper self-marks)
  - analytics_followups     — mentor follow-up actions

Enabled with SEED_ANALYTICS_DEMO=1. Never runs against real MongoDB.
"""
from datetime import date, datetime, timedelta, timezone

from db import (
    ANALYTICS_CONSENTS,
    ANALYTICS_FOLLOWUPS,
    ANALYTICS_SUMMARIES,
    ANALYTICS_TEST_HISTORY,
    ANALYTICS_TRENDS,
    STUDENT_MESSAGES,
    WHATSAPP_LOG,
    get_db,
)

TODAY = date.today()
NOW = datetime.now(timezone.utc).isoformat()


def _weeks_ago(n: int) -> str:
    from week_window import week_start
    return (week_start(TODAY) - timedelta(weeks=n)).isoformat()


def _days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


STUDENTS = [
    {"studentId": "UMP2407", "studentName": "Aarav Sharma", "batch": "Achievers 2.0", "group": "Group I", "joinedOn": "2025-12-01"},
    {"studentId": "UMP2411", "studentName": "Diya Patel", "batch": "Super 30", "group": "Group I", "joinedOn": "2026-01-12"},
    {"studentId": "UMP2418", "studentName": "Rohan Verma", "batch": "Super 30", "group": "Group II", "joinedOn": "2026-02-03"},
    {"studentId": "UMP2425", "studentName": "Sneha Iyer", "batch": "Achievers 2.0", "group": "Group II", "joinedOn": "2026-03-18"},
]

# studentId → list of (chapterId, subject, band, attempts, accuracy, lastActiveDaysAgo, weakTags)
SUMMARIES = {
    "UMP2407": [
        ("1.1 Accounting Standards", "Accounts", "Strong", 14, "70-84", 1, []),
        ("1.2 Accounting Process", "Accounts", "Mastered", 18, "85-100", 0, []),
        ("2.1 Company Law", "Law", "Medium", 9, "50-69", 2, ["charge registration"]),
        ("2.2 Contract Act", "Law", "Weak", 6, "0-49", 3, ["consideration", "free consent"]),
        ("3.1 Income from House Property", "Taxation", "Medium", 8, "50-69", 1, ["annual value"]),
        ("3.2 Capital Gains", "Taxation", "Strong", 11, "70-84", 0, []),
    ],
    "UMP2411": [
        ("1.1 Accounting Standards", "Accounts", "Mastered", 16, "85-100", 0, []),
        ("1.3 Bank Reconciliation", "Accounts", "Strong", 12, "70-84", 1, []),
        ("2.1 Company Law", "Law", "Medium", 7, "50-69", 2, ["prospectus"]),
        ("2.2 Contract Act", "Law", "Strong", 13, "70-84", 1, []),
        ("3.1 Income from House Property", "Taxation", "Weak", 5, "0-49", 4, ["annual value", "deductions"]),
    ],
    "UMP2418": [
        ("4.1 Costing Methods", "Costing", "Weak", 6, "0-49", 2, ["process costing"]),
        ("4.2 Cost Sheet", "Costing", "Medium", 8, "50-69", 1, []),
        ("5.1 Audit Evidence", "Audit", "Medium", 9, "50-69", 2, ["vouching"]),
        ("6.1 Financial Management", "FM", "Weak", 5, "0-49", 5, ["time value of money"]),
        ("6.2 Capital Budgeting", "FM", "Not assessed", 0, "0-49", 12, []),
    ],
}

# studentId → chapterId → weekly bands (oldest → newest)
TRENDS = {
    "UMP2407": {
        "1.1 Accounting Standards": ["Weak", "Weak", "Medium", "Medium", "Strong", "Strong"],
        "2.2 Contract Act": ["Strong", "Strong", "Medium", "Medium", "Weak", "Weak"],
        "3.2 Capital Gains": ["Medium", "Medium", "Medium", "Strong", "Strong", "Strong"],
    },
    "UMP2411": {
        "2.1 Company Law": ["Weak", "Weak", "Medium", "Medium", "Medium", "Strong"],
        "1.1 Accounting Standards": ["Strong", "Strong", "Mastered", "Mastered", "Mastered", "Mastered"],
    },
    "UMP2418": {
        "4.1 Costing Methods": ["Strong", "Medium", "Medium", "Weak", "Weak", "Weak"],
        "5.1 Audit Evidence": ["Weak", "Weak", "Medium", "Medium", "Medium", "Medium"],
    },
}

ACC_BY_BAND = {"Mastered": "85-100", "Strong": "70-84", "Medium": "50-69", "Weak": "0-49", "Not assessed": "0-49"}

TEST_ENTRIES = [
    ("UMP2407", "acc-as-1", "mcq-test", "Accounting Standards — Test 1", "Accounts", 3, 12, 16, 75, None),
    ("UMP2407", "acc-paper-1", "paper-test", "Accounting Standards — Batch Test", "Accounts", 1, 38, 60, None, True),
    ("UMP2411", "acc-as-1", "mcq-test", "Accounting Standards — Test 1", "Accounts", 3, 14, 16, 88, None),
    ("UMP2411", "acc-paper-1", "paper-test", "Accounting Standards — Batch Test", "Accounts", 1, None, 60, None, None),
    ("UMP2418", "acc-as-1", "mcq-test", "Accounting Standards — Test 1", "Accounts", 3, 9, 16, 56, None),
    ("UMP2418", "acc-paper-1", "paper-test", "Accounting Standards — Batch Test", "Accounts", 1, 27, 60, None, True),
    ("UMP2407", "law-contract-2", "mcq-test", "Contract Act — Test 2", "Law", 2, 7, 12, 58, None),
    ("UMP2411", "law-contract-2", "mcq-test", "Contract Act — Test 2", "Law", 2, 10, 12, 83, None),
]

MESSAGES = [
    {"studentId": "UMP2407", "studentName": "Aarav Sharma", "batch": "Achievers 2.0", "unread": 0, "msgs": [
        {"from": "student", "text": "Sir, AS-10 valuation of inventory — cost or NRV, which one do we apply when NRV falls below cost?", "mins": 300},
        {"from": "mentor", "text": "Good question Aarav. Apply the lower of cost and NRV — write inventory down to NRV and recognise the loss in P&L. Revise AS 2 examples once.", "mins": 240},
        {"from": "student", "text": "Understood sir, thank you! Will revise tonight.", "mins": 200},
    ]},
    {"studentId": "UMP2411", "studentName": "Diya Patel", "batch": "Super 30", "unread": 1, "msgs": [
        {"from": "student", "text": "Sir I submitted the Accounting Standards paper but I am confused about the marking scheme for Q3. Can we discuss in the next class?", "mins": 90},
    ]},
    {"studentId": "UMP2418", "studentName": "Rohan Verma", "batch": "Super 30", "unread": 2, "msgs": [
        {"from": "student", "text": "Sir process costing equivalent units concept is not clearing from the notes.", "mins": 600},
        {"from": "student", "text": "Also can you share extra practice questions for costing methods?", "mins": 45},
    ]},
]


def _mins_ago(n):
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


FOLLOWUPS = [
    {
        "studentId": "UMP2418",
        "title": "Discuss declining Costing performance",
        "priority": "high",
        "status": "open",
        "rule": "declining_trend",
        "createdAt": NOW,
        "notes": [],
    },
    {
        "studentId": "UMP2411",
        "title": "Remind to enter self marks for Accounting Standards paper",
        "priority": "medium",
        "status": "in_progress",
        "rule": None,
        "createdAt": NOW,
        "notes": [{"by": "mentor", "note": "Messaged on the app messenger.", "at": NOW}],
    },
]


async def seed_analytics_demo() -> dict:
    db = get_db()
    by_id = {s["studentId"]: s for s in STUDENTS}

    # Consents (Sneha keeps sharing OFF to show the off state)
    for s in STUDENTS:
        sharing = s["studentId"] != "UMP2425"
        await db[ANALYTICS_CONSENTS].update_one(
            {"studentId": s["studentId"]},
            {"$set": {
                "studentId": s["studentId"], "sharing": sharing, "updatedAt": NOW, "device": "demo-seed",
                "studentName": s["studentName"], "batch": s["batch"], "joinedOn": s["joinedOn"],
            }},
            upsert=True,
        )

    # Chapter summaries
    for sid, rows in SUMMARIES.items():
        meta = by_id[sid]
        for chapter_id, subject, band, attempts, accuracy, days_ago, tags in rows:
            await db[ANALYTICS_SUMMARIES].update_one(
                {"studentId": sid, "chapterId": chapter_id},
                {"$set": {
                    "studentId": sid,
                    "chapterId": chapter_id,
                    "subject": subject,
                    "group": meta["group"],
                    "masteryBand": band,
                    "attemptCount": attempts,
                    "accuracyRange": accuracy,
                    "lastActivityDate": _days_ago(days_ago),
                    "weakConceptTags": tags,
                    "syncedAt": NOW,
                }},
                upsert=True,
            )

    # Weekly trends
    for sid, chapters in TRENDS.items():
        for chapter_id, bands in chapters.items():
            for i, band in enumerate(bands):
                week = _weeks_ago(len(bands) - 1 - i)
                await db[ANALYTICS_TRENDS].update_one(
                    {"studentId": sid, "chapterId": chapter_id, "weekStart": week},
                    {"$set": {
                        "studentId": sid,
                        "chapterId": chapter_id,
                        "weekStart": week,
                        "masteryBand": band,
                        "attemptCount": 3 + i,
                        "accuracyRange": ACC_BY_BAND.get(band, "0-49"),
                        "syncedAt": NOW,
                    }},
                    upsert=True,
                )

    # Test history (MCQ auto-scores + paper self marks)
    for sid, test_id, kind, title, subject, days_ago, score, total, pct, self_marks in TEST_ENTRIES:
        meta = by_id[sid]
        await db[ANALYTICS_TEST_HISTORY].update_one(
            {"studentId": sid, "testId": test_id, "kind": kind, "entryId": f"{sid}-{test_id}"},
            {"$set": {
                "entryId": f"{sid}-{test_id}",
                "studentId": sid,
                "studentName": meta["studentName"],
                "batch": meta["batch"],
                "testId": test_id,
                "kind": kind,
                "title": title,
                "subject": subject,
                "at": f"{_days_ago(days_ago)}T10:30:00+00:00",
                "score": score,
                "total": total,
                "scorePct": pct,
                "selfMarks": self_marks,
                "syncedAt": NOW,
            }},
            upsert=True,
        )

    # Follow-ups
    for i, f in enumerate(FOLLOWUPS):
        await db[ANALYTICS_FOLLOWUPS].update_one(
            {"studentId": f["studentId"], "title": f["title"]},
            {"$set": {**f, "followupId": f"demo-followup-{i + 1}"}},
            upsert=True,
        )

    # Messenger threads
    for thread in MESSAGES:
        messages = [
            {"id": f"demo-{thread['studentId']}-{i}", "from": m["from"], "text": m["text"], "at": _mins_ago(m["mins"])}
            for i, m in enumerate(thread["msgs"])
        ]
        await db[STUDENT_MESSAGES].update_one(
            {"studentId": thread["studentId"]},
            {"$set": {
                "studentId": thread["studentId"],
                "studentName": thread["studentName"],
                "batch": thread["batch"],
                "messages": messages,
                "unreadForMentor": thread["unread"],
                "updatedAt": messages[-1]["at"] if messages else NOW,
            }},
            upsert=True,
        )

    # WhatsApp delivery log for the demo student messages (dual-channel proof)
    for thread in MESSAGES:
        for i, m in enumerate(thread["msgs"]):
            if m["from"] != "student":
                continue
            await db[WHATSAPP_LOG].insert_one({
                "at": _mins_ago(m["mins"]),
                "to": "919820000000",
                "purpose": "student_message",
                "status": "sent",
                "detail": f"message from {thread['studentName']} mirrored to WhatsApp",
            })

    return {"students": len(STUDENTS), "summaries": sum(len(v) for v in SUMMARIES.values()), "tests": len(TEST_ENTRIES)}


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(seed_analytics_demo()))
