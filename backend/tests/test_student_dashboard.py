"""Mongo-backed student dashboard reads."""
from datetime import date, timedelta

# Dates in these fixtures must stay relative to "today": the stats route windows on
# the rolling last 7 days, so a hardcoded date silently rots into a failure.
RECENT_DAY = (date.today() - timedelta(days=1)).isoformat()
TODAY_DAY = date.today().isoformat()


def seed_student_auth(client, mentor_headers, student_id="UMP0001"):
    result = client.post("/api/student-auth/import", headers=mentor_headers, json={"students":[{"studentId":student_id,"password":"synthetic-dashboard","attempt":"Jan 2027","batch":"Fixture"}]})
    assert result.status_code == 200, result.text
    return {"X-Student-Id":student_id,"X-Session-Password":"synthetic-dashboard"}


def test_dashboard_import_and_reads(client, mentor_headers):
    actor = seed_student_auth(client, mentor_headers)
    imported = client.post(
        "/api/student-dashboard/import",
        headers=mentor_headers,
        json={
            "announcements": [{"id": "A1", "title": "Hello", "message": "World"}],
            "leaderboard": [{"rank": 1, "studentId": "UMP0001", "studentName": "A"}],
            "notes": [{"id": "N1", "title": "PDF", "audience": "All Batches", "group": "Both Groups"}],
            "students": [
                {
                    "studentId": "UMP0001",
                    "stats": {"weeklyHours": 12, "streak": 3},
                    "studyLog": [{"date": RECENT_DAY, "topic": "FM", "hours": 9}],
                    "reports": [{"weekOf": "10 Aug – 16 Aug", "weeklyHours": 55}],
                    "mentorNotes": [{"date": "2026-08-12", "note": "Keep going"}],
                    "feedback": [],
                }
            ],
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["students"] == 1

    status = client.get("/api/student-dashboard/status").json()
    assert status["shared"] is True
    assert status["students"] == 1
    assert status["announcements"] == 1

    announcements = client.post("/api/student-dashboard/get", headers=actor, json={"action":"getAnnouncements"})
    assert announcements.status_code == 503  # Classification/membership evidence required.

    stats = client.post("/api/student-dashboard/get", headers=actor,
        json={"action": "getStats", "payload": {"studentId": "UMP0001"}},
    ).json()
    assert stats["found"] is True
    # getStats recomputes from the study log, so it reports the 9 hours actually
    # logged yesterday rather than echoing the imported placeholder value.
    assert stats["result"]["weeklyHours"] == 9.0
    assert stats["result"]["totalHours"] == 9.0

    missing = client.post("/api/student-dashboard/get", headers=actor, json={"action":"getStats","payload":{"studentId":"UMP9999"}})
    assert missing.status_code == 403  # An authenticated owner cannot probe a different ID.

    notes = client.post("/api/student-dashboard/get", headers=actor, json={"action":"notes.listForStudent","payload":{"studentId":"UMP0001"}})
    assert notes.status_code == 503  # No guessed publication scope.

    written = client.post("/api/student-dashboard/write", headers=actor,
        json={
            "action": "addStudyLog",
            "payload": {"studentId": "UMP0001", "date": TODAY_DAY, "hours": 2, "subjects": "Audit"},
        },
    )
    assert written.status_code == 200, written.text
    assert written.json()["ok"] is True
    stats = client.post("/api/student-dashboard/get", headers=actor,
        json={"action": "getStats", "payload": {"studentId": "UMP0001"}},
    ).json()["result"]
    # yesterday's 9 hours + today's 2 hours, both inside the rolling 7-day window
    assert stats["weeklyHours"] == 11.0
    log = client.post("/api/student-dashboard/get", headers=actor,
        json={"action": "getStudyLog", "payload": {"studentId": "UMP0001"}},
    ).json()["result"]
    assert log[0]["topic"] == "Audit"

    denied = client.post("/api/student-dashboard/write", headers=actor,
        json={"action": "announcements.create", "payload": {"title": "Live", "body": "Now"}},
    )
    assert denied.status_code == 403
    anns = client.post("/api/student-dashboard/get", headers=actor, json={"action":"getAnnouncements"})
    assert anns.status_code == 503
