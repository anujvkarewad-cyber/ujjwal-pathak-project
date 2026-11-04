"""Photo parsing must survive real-world model output.

Groq's vision model does not always return clean JSON: it wraps it in fences,
adds prose, leaves trailing commas, or answers with a bare list of days. The
mentor's upload must still fill the rows, so these shapes are locked down here.
No network is used — the parsing helpers are pure functions.
"""
import pytest

from routers import target_plans


SHAPES = {
    "fenced": '```json\n{"name":"X","days":[{"day":1,"entries":[{"subject":"Cost","topic":"Chap 1","hours":2,"kind":"study"}]}]}\n```',
    "prose_around": 'Here is the plan: {"name":"X","days":[{"day":1,"entries":[{"topic":"Chap 1"}]}]} Hope it helps!',
    "trailing_comma": '{"name":"X","days":[{"day":1,"entries":[{"topic":"A"},]},]}',
    "wrapped": '{"plan":{"name":"X","days":[{"day":1,"entries":[{"topic":"A"}]}]}}',
    "bare_list": '[{"day":1,"entries":[{"topic":"A"}]}]',
    "flat_day": '{"days":[{"day":1,"subject":"Audit","topic":"SA 200","hours":1,"kind":"study"}]}',
    "string_entries": '{"days":[{"day":1,"entries":["Taxation chap 1","Cost chap 2"]}]}',
    "tasks_key": '{"days":[{"day":1,"tasks":[{"subject":"FM","topic":"Ratio","hours":1.5}]}]}',
}


@pytest.mark.parametrize("name,raw", list(SHAPES.items()))
def test_every_model_shape_yields_usable_days(name, raw):
    parsed = target_plans._extract_plan_json(raw)
    assert parsed, f"{name}: nothing extracted"
    days = target_plans._normalize_parsed_days(parsed)
    assert days, f"{name}: no usable day"
    first = days[0]["entries"][0]
    assert first["topic"]
    assert first["subject"]
    assert first["kind"] in ("study", "revision", "test")
    assert set(first) >= {"subject", "topic", "hours", "kind"}


def test_missing_subject_defaults_instead_of_dropping_the_row():
    days = target_plans._normalize_parsed_days(
        target_plans._extract_plan_json('{"days":[{"entries":[{"topic":"Revision of chap 1"}]}]}')
    )
    assert days and days[0]["entries"][0]["subject"] == "All"


def test_garbage_returns_no_days_instead_of_raising():
    for junk in ("", "I could not read this image.", "{broken", "null"):
        parsed = target_plans._extract_plan_json(junk)
        days = target_plans._normalize_parsed_days(parsed) if parsed else []
        assert days == []


def test_day_numbers_are_sequential_even_when_the_model_misnumbers():
    raw = '{"days":[{"day":7,"entries":[{"topic":"a"}]},{"day":9,"entries":[{"topic":"b"}]}]}'
    days = target_plans._normalize_parsed_days(target_plans._extract_plan_json(raw))
    assert [d["day"] for d in days] == [1, 2]


# ── the failure that broke the owner's real poster: the answer was cut off ──────
TRUNCATED = {
    "missing_final_brace": '{"name":"X","days":[{"day":1,"entries":[{"subject":"Taxation","topic":"AS 13","hours":4,"kind":"study"}]}]',
    "missing_two_closers": '{"name":"X","days":[{"day":1,"entries":[{"subject":"Taxation","topic":"AS 13","hours":4,"kind":"study"}]',
    "cut_mid_string": '{"name":"X","days":[{"day":1,"entries":[{"subject":"Taxation","topic":"AS 13","hours":4,"kind":"study"},{"subject":"Taxat',
    "cut_mid_key": '{"name":"X","days":[{"day":1,"entries":[{"subject":"Taxation","topic":"AS 13","hours":4,"kind":"study"},{"subj',
    "cut_before_last_entry": '{"name":"X","days":[{"day":1,"entries":[{"subject":"Taxation","topic":"AS 13","hours":4,"kind":"study"},{"subject":"Cost","topic":"Chap 2","hours":3,"kind":"study"},{"subject":"Aud',
}


@pytest.mark.parametrize("name,raw", list(TRUNCATED.items()))
def test_cut_off_answers_still_yield_the_days_that_were_read(name, raw):
    parsed = target_plans._extract_plan_json(raw)
    assert parsed, f"{name}: truncated answer was rejected"
    days = target_plans._normalize_parsed_days(parsed)
    assert days, f"{name}: no usable day after repair"
    assert days[0]["entries"][0]["topic"] == "AS 13"
    assert days[0]["entries"][0]["hours"] == 4


def test_balancer_ignores_brackets_inside_strings():
    raw = '{"name":"Day [1] {special}","days":[{"day":1,"entries":[{"topic":"a [b] c","hours":1}]}]'
    parsed = target_plans._extract_plan_json(raw)
    assert parsed and parsed["name"] == "Day [1] {special}"
    assert target_plans._normalize_parsed_days(parsed)[0]["entries"][0]["topic"] == "a [b] c"


# ── rate limits (Groq free plan) and payload size ──────────────────────────────
class _FakeResp:
    def __init__(self, headers=None, text=""):
        self.headers = headers or {}
        self.text = text


def test_retry_after_is_read_from_the_header():
    assert target_plans._retry_after_seconds(_FakeResp({"retry-after": "7"})) == 7.0


def test_retry_after_falls_back_to_the_message_hint():
    hint = "Rate limit reached. Please try again in 12.5s."
    assert target_plans._retry_after_seconds(_FakeResp({}, hint)) == 12.5


def test_retry_after_absent_means_zero():
    assert target_plans._retry_after_seconds(_FakeResp({}, "boom")) == 0.0


def test_rate_limit_message_tells_the_mentor_to_wait(monkeypatch):
    """A 429 must read as 'wait a minute', not as 'your photo is unreadable'."""
    import io
    from PIL import Image
    from starlette.datastructures import UploadFile, Headers

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, format="JPEG")
    buf.seek(0)
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")

    class _Boom:
        status_code = 429
        headers = {}
        text = "rate limit"

        def json(self):
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Boom()

    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: _Client())
    import asyncio
    import pytest as _pytest
    upload = UploadFile(file=buf, filename="p.jpg", headers=Headers({"content-type": "image/jpeg"}))
    with _pytest.raises(Exception) as err:
        asyncio.run(target_plans.parse_plan_photo(file=upload, _mentor=None))
    assert "rate limit" in str(err.value).lower()
    assert "wait about a minute" in str(err.value).lower()


def test_large_photo_is_downscaled_before_upload():
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1086, 1448), "white").save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    small, ctype = target_plans._shrink_for_vision(data, "image/jpeg")
    assert ctype == "image/jpeg"
    assert max(Image.open(io.BytesIO(small)).size) <= 1400
    assert len(small) < len(data)


def test_shrink_never_raises_on_junk():
    junk = b"not-an-image"
    out, ctype = target_plans._shrink_for_vision(junk, "image/png")
    assert out == junk and ctype == "image/png"
