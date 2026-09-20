"""Mongo-backed student dashboard reads."""


def test_dashboard_import_and_reads(client, mentor_headers):
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
                    "studyLog": [{"date": "2026-08-17", "topic": "FM", "hours": 9}],
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

    announcements = client.post(
        "/api/student-dashboard/get", json={"action": "getAnnouncements"}
    ).json()
    assert announcements["found"] is True
    assert announcements["result"][0]["title"] == "Hello"

    stats = client.post(
        "/api/student-dashboard/get",
        json={"action": "getStats", "payload": {"studentId": "UMP0001"}},
    ).json()
    assert stats["found"] is True
    assert stats["result"]["weeklyHours"] == 12

    missing = client.post(
        "/api/student-dashboard/get",
        json={"action": "getStats", "payload": {"studentId": "UMP9999"}},
    ).json()
    assert missing["found"] is False

    notes = client.post(
        "/api/student-dashboard/get",
        json={"action": "notes.listForStudent", "payload": {"studentId": "UMP0001"}},
    ).json()
    assert notes["found"] is True
    assert notes["result"][0]["id"] == "N1"

    written = client.post(
        "/api/student-dashboard/write",
        json={
            "action": "addStudyLog",
            "payload": {"studentId": "UMP0001", "date": "2026-08-19", "hours": 2, "subjects": "Audit"},
        },
    )
    assert written.status_code == 200, written.text
    assert written.json()["ok"] is True
    stats = client.post(
        "/api/student-dashboard/get",
        json={"action": "getStats", "payload": {"studentId": "UMP0001"}},
    ).json()["result"]
    assert stats["weeklyHours"] == 14
    log = client.post(
        "/api/student-dashboard/get",
        json={"action": "getStudyLog", "payload": {"studentId": "UMP0001"}},
    ).json()["result"]
    assert log[0]["topic"] == "Audit"

    client.post(
        "/api/student-dashboard/write",
        json={"action": "announcements.create", "payload": {"title": "Live", "body": "Now"}},
    )
    anns = client.post("/api/student-dashboard/get", json={"action": "getAnnouncements"}).json()["result"]
    assert anns[0]["title"] == "Live"
