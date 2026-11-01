"""Announcement publish -> device push wiring.

The mentor dashboard publishes announcements via Apps Script (in-app + sheet).
This endpoint is the push leg: publish must also reach the students' phones,
audience-filtered, without touching the behavior-notification caps.
"""


def _fake_push(captured):
    async def fake(title, body, *, link="", tag="", batch="", group="", throttle_s=0.15):
        captured.append(
            {"title": title, "body": body, "link": link, "tag": tag, "batch": batch, "group": group}
        )
        return 3
    return fake


def test_notify_requires_auth(client):
    res = client.post(
        "/api/student-dashboard/announcements/notify",
        json={"title": "Hello", "body": "World"},
    )
    assert res.status_code in (401, 403)


def test_notify_all_batches_pushes_everyone(client, mentor_headers, monkeypatch):
    import push as push_service

    captured: list = []
    monkeypatch.setattr(push_service, "push_to_all", _fake_push(captured))

    res = client.post(
        "/api/student-dashboard/announcements/notify",
        headers=mentor_headers,
        json={"title": "Test Series Live", "body": "Mock test 4 is open.", "audience": "All Batches"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["sent"] == 3
    assert data["audience"] == "All Batches"
    assert len(captured) == 1
    call = captured[0]
    assert "Test Series Live" in call["title"]
    assert "Mock test 4 is open." in call["body"]
    assert call["batch"] == ""  # no filter -> every registered device
    assert call["link"] == "home"
    assert call["tag"].startswith("ann-")


def test_notify_specific_batch_filters_audience(client, mentor_headers, monkeypatch):
    import push as push_service

    captured: list = []
    monkeypatch.setattr(push_service, "push_to_all", _fake_push(captured))

    res = client.post(
        "/api/student-dashboard/announcements/notify",
        headers=mentor_headers,
        json={"title": "Batch 1 meet", "body": "Sunday 11 AM.", "audience": "Before Result Batch 1"},
    )
    assert res.status_code == 200, res.text
    assert captured[0]["batch"] == "Before Result Batch 1"


def test_notify_empty_title_rejected(client, mentor_headers):
    res = client.post(
        "/api/student-dashboard/announcements/notify",
        headers=mentor_headers,
        json={"title": "   ", "body": "x"},
    )
    assert res.status_code in (400, 422)  # blank title -> handler 400 / pydantic 422


def test_notify_body_optional(client, mentor_headers, monkeypatch):
    import push as push_service

    captured: list = []
    monkeypatch.setattr(push_service, "push_to_all", _fake_push(captured))

    res = client.post(
        "/api/student-dashboard/announcements/notify",
        headers=mentor_headers,
        json={"title": "Holiday notice"},
    )
    assert res.status_code == 200, res.text
    assert captured[0]["body"]  # fallback copy, never empty
