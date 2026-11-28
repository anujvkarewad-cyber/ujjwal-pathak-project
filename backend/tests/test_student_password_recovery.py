"""Tests for student self-service account recovery routes on /api/student-auth.

Covers:
  - POST /api/student-auth/forgot-password
  - POST /api/student-auth/verify-otp
  - POST /api/student-auth/reset-password
  - 5-digit student IDs (UMP10000) and common prefix/zero mistypes
  - Upstream error isolation (never leaking STUDENT_ADMIN_SCRIPT_URL or adminKey)
  - End-to-end compatibility with Super 75 Password Reset's /api/student-auth/import sync
"""
import httpx
import pytest


def test_recovery_routes_normalize_inputs_and_complete_reset_flow(client, monkeypatch):
    import routers.student_auth as student_auth

    script_url = "https://script.google.com/macros/s/test-super75-reset/exec"
    monkeypatch.setattr(student_auth.settings, "student_admin_script_url", script_url)
    monkeypatch.setattr(student_auth.settings, "student_import_key", "super-secret-import-key")

    real_async_client = httpx.AsyncClient
    upstream_calls = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("upstream error", request=None, response=None)

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None):
            upstream_calls.append((url, json))
            action = (json or {}).get("action")
            payload = (json or {}).get("payload") or {}
            # Student-facing recovery must never attach adminKey.
            assert "adminKey" not in payload

            if action == "forgotPassword":
                return FakeResponse(
                    200,
                    {
                        "result": {
                            "success": True,
                            "message": "A verification code has been sent to iq***5@gmail.com.",
                        }
                    },
                )
            if action == "verifyOTP":
                return FakeResponse(
                    200,
                    {
                        "result": {
                            "success": True,
                            "message": "Code verified. You can now set a new password.",
                        }
                    },
                )
            if action == "resetPassword":
                # Simulate Super 75 Password Reset syncing the reset password back to Mongo
                # concurrently while /reset-password is still awaiting the Apps Script response.
                transport = httpx.ASGITransport(app=client.app)
                async with real_async_client(
                    transport=transport, base_url="http://testserver"
                ) as asgi_client:
                    imp = await asgi_client.post(
                        "/api/student-auth/import",
                        headers={"X-UMP-Import": "super-secret-import-key"},
                        json={
                            "students": [
                                {
                                    "studentId": payload["studentId"],
                                    "studentName": "Iqra sayyed",
                                    "email": "iqrasayyed135@gmail.com",
                                    "caLevel": "CA Intermediate",
                                    "group": "Group 1",
                                    "attempt": "Jan 2027",
                                    "batch": "Last 25 days planner batch",
                                    "password": payload["password"],
                                    "passwordChanged": True,
                                    "forcePasswordReset": True,
                                }
                            ]
                        },
                    )
                assert imp.status_code == 200
                return FakeResponse(
                    200,
                    {
                        "result": {
                            "success": True,
                            "message": "Password reset successful. Sign in with your new password.",
                        }
                    },
                )
            raise AssertionError(f"Unexpected action: {action}")

    monkeypatch.setattr(student_auth.httpx, "AsyncClient", FakeAsyncClient)

    # Step 1: Forgot password with 5-digit ID + mixed-case email
    fp = client.post(
        "/api/student-auth/forgot-password",
        json={"studentId": "ump10000", "email": "  IqraSayyed135@Gmail.com "},
    )
    assert fp.status_code == 200
    assert fp.json() == {
        "result": {
            "success": True,
            "message": "A verification code has been sent to iq***5@gmail.com.",
        }
    }

    # Step 2: Verify OTP using nested payload shape and swapped prefix typo (UPM10000 -> UMP10000)
    vo = client.post(
        "/api/student-auth/verify-otp",
        json={"payload": {"studentId": "UPM10000", "otp": " 482910 "}},
    )
    assert vo.status_code == 200
    assert vo.json()["result"]["success"] is True

    # Step 3: Reset password
    rp = client.post(
        "/api/student-auth/reset-password",
        json={"studentId": "UMP10000", "password": "NewStrongPass#2027"},
    )
    assert rp.status_code == 200
    assert rp.json()["result"]["success"] is True

    assert upstream_calls == [
        (
            script_url,
            {
                "action": "forgotPassword",
                "payload": {"studentId": "UMP10000", "email": "iqrasayyed135@gmail.com"},
            },
        ),
        (
            script_url,
            {
                "action": "verifyOTP",
                "payload": {"studentId": "UMP10000", "otp": "482910"},
            },
        ),
        (
            script_url,
            {
                "action": "resetPassword",
                "payload": {"studentId": "UMP10000", "password": "NewStrongPass#2027"},
            },
        ),
    ]

    # Step 4: Student can immediately sign in against Mongo with the new password
    login = client.post(
        "/api/student-auth/login",
        json={"studentId": "UMP10000", "password": "NewStrongPass#2027"},
    )
    assert login.status_code == 200
    body = login.json()["result"]
    assert body["success"] is True
    assert body["studentId"] == "UMP10000"
    assert body["forcePasswordChange"] is False


def test_recovery_validation_rejects_bad_input_without_calling_upstream(client, monkeypatch):
    import routers.student_auth as student_auth

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Upstream script should not be called for invalid input")

    monkeypatch.setattr(student_auth.httpx, "AsyncClient", fail_if_called)

    fp = client.post("/api/student-auth/forgot-password", json={"studentId": "", "email": ""})
    assert fp.status_code == 200
    assert fp.json()["result"]["success"] is False

    vo = client.post("/api/student-auth/verify-otp", json={"studentId": "UMP10000", "otp": "12ab"})
    assert vo.status_code == 200
    assert vo.json()["result"] == {
        "success": False,
        "message": "Enter the complete 6-digit code.",
    }

    rp = client.post(
        "/api/student-auth/reset-password",
        json={"studentId": "UMP10000", "password": "123"},
    )
    assert rp.status_code == 200
    assert rp.json()["result"]["success"] is False


def test_recovery_upstream_errors_never_leak_script_url(client, monkeypatch):
    import routers.student_auth as student_auth

    secret_url = "https://script.google.com/macros/s/SECRET_DEPLOYMENT_ID/exec"

    # Unconfigured script URL -> 503
    monkeypatch.setattr(student_auth.settings, "student_admin_script_url", "")
    unconfigured = client.post(
        "/api/student-auth/forgot-password",
        json={"studentId": "UMP10000", "email": "iqrasayyed135@gmail.com"},
    )
    assert unconfigured.status_code == 503
    assert "SECRET_DEPLOYMENT_ID" not in unconfigured.text

    # Misconfigured upstream returning {"error": "Unsupported action"} -> 502 with safe detail
    class UnsupportedActionClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None):
            class Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"error": "Unsupported action"}

            return Resp()

    monkeypatch.setattr(student_auth.settings, "student_admin_script_url", secret_url)
    monkeypatch.setattr(student_auth.httpx, "AsyncClient", UnsupportedActionClient)

    bad_upstream = client.post(
        "/api/student-auth/forgot-password",
        json={"studentId": "UMP10000", "email": "iqrasayyed135@gmail.com"},
    )
    assert bad_upstream.status_code == 502
    assert "SECRET_DEPLOYMENT_ID" not in bad_upstream.text
    assert "Unsupported action" not in bad_upstream.text
