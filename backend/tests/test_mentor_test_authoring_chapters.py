"""Required chapter routing and optional mentor-entered test names."""
import pytest

CHAPTER = "Ch 1 — The Nature of Auditing"


@pytest.mark.parametrize("title", [None, ""])
def test_test_name_is_optional_and_defaults_to_the_selected_chapter(client, mentor_headers, title):
    response = client.post(
        "/api/mentor/tests",
        headers=mentor_headers,
        json={
            "title": title,
            "kind": "paper-test",
            "subject": "Audit",
            "chapters": [CHAPTER],
        },
    )

    assert response.status_code == 201, response.text
    test = response.json()["test"]
    assert test["title"] == f"Practice test — {CHAPTER}"
    assert test["chapters"] == [CHAPTER]


@pytest.mark.parametrize("payload", [
    {"subject": "Audit"},
    {"subject": "Audit", "chapters": []},
    {"subject": "Audit", "chapters": ["   "]},
])
def test_test_creation_rejects_a_missing_or_blank_chapter(client, mentor_headers, payload):
    response = client.post("/api/mentor/tests", headers=mentor_headers, json=payload)
    assert response.status_code == 422
