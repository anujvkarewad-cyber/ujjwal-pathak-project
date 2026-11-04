#!/usr/bin/env python3
"""Error watch — the daily "is anything broken?" check.

Run it any time (or from cron / a scheduled Cloud Run job):

    python3 scripts/watch_errors.py            # last 24 h
    python3 scripts/watch_errors.py --hours 2  # last 2 h

It reads the Cloud Run request logs and answers the only question that
matters: "is any student-facing endpoint failing right now?"

Exit 0 = clean, 1 = there are 5xx errors (with the endpoints listed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

PROJECT = os.environ.get("PROJECT", "ump-dashboard")
SERVICE = os.environ.get("SERVICE", "ujjwal-pathak-app")
REGION = os.environ.get("REGION", "asia-south1")

# Endpoints a student uses. A 5xx here is a student staring at an error.
STUDENT_ENDPOINTS = (
    "/api/ai/target-plan-days",
    "/api/student-dashboard/get",
    "/api/student-dashboard/leaderboard",
    "/api/smart-targets/student/dashboard",
    "/api/student-auth/login",
    "/api/targets/complete",
    "/api/mentor-workspace/student/",
)


def _metadata_token() -> str:
    """A service-account token from the Cloud Run metadata server.

    Lets the watch run inside a scheduled Cloud Run job, where the gcloud CLI
    is not installed.
    """
    import urllib.request
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def _logging_api(filt: str) -> list:
    """Read the logs through the Cloud Logging API (works inside Cloud Run)."""
    import urllib.parse
    import urllib.request
    token = _metadata_token()
    body = json.dumps({
        "resourceNames": [f"projects/{PROJECT}"],
        "filter": filt,
        "orderBy": "timestamp desc",
        "pageSize": 2000,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://logging.googleapis.com/v2/entries:list",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("entries") or []


def run_gcloud(args: list[str]) -> str:
    cmd = ["gcloud", "logging", "read"] + args + [
        "--project=" + PROJECT, "--format=json", "--limit=2000"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gcloud logging read failed")
    return out.stdout


class WatchUnavailable(RuntimeError):
    """The logs could not be read at all."""


def _entries(filt: str) -> list:
    """Read log entries, preferring the API and falling back to the CLI.

    Raises WatchUnavailable when neither path works: a watch that cannot see
    must say so, never report "all clear".
    """
    api_error = None
    try:
        return _logging_api(filt)
    except Exception as exc:
        api_error = exc
    try:
        raw = run_gcloud([filt])
        return json.loads(raw or "[]")
    except Exception as exc:
        raise WatchUnavailable(
            f"could not read the logs: API said {api_error}; CLI said {exc}") from exc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    # gcloud logging read takes a single filter expression as one argument.
    filt = (f'resource.type=cloud_run_revision '
            f'AND resource.labels.service_name={SERVICE} '
            f'AND httpRequest.status>=500 '
            f'AND timestamp>="{since_iso}"')
    try:
        entries = _entries(filt)
    except WatchUnavailable as exc:
        print(f"UMP error watch - {SERVICE}")
        print(f"  ✗ COULD NOT READ THE LOGS - this is NOT an all-clear")
        print(f"    {exc}")
        return 2

    # Which revision is serving traffic right now? Only errors on THAT
    # revision are live problems; older ones are history.
    current = ""
    try:
        import urllib.request
        token = _metadata_token()
        url = (f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}"
               f"/services/{SERVICE}")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = ((data.get("latestReadyRevision") or "").rsplit("/", 1)[-1]).strip()
    except Exception:
        try:
            out = subprocess.run(
                ["gcloud", "run", "services", "describe", SERVICE,
                 "--region=" + REGION, "--project=" + PROJECT,
                 "--format=value(status.latestReadyRevisionName)"],
                capture_output=True, text=True, timeout=60)
            current = out.stdout.strip()
        except Exception:
            pass

    by_endpoint = Counter()
    by_revision = Counter()
    student_hits = 0
    live_entries = []
    for entry in entries:
        req = entry.get("httpRequest") or {}
        status = req.get("status")
        url = req.get("requestUrl") or ""
        path = url.split("?")[0]
        resource = entry.get("resource") or {}
        labels = resource.get("labels") or {}
        revision = labels.get("revision_name") or resource.get("revisionName") or ""
        by_endpoint[(status, path)] += 1
        by_revision[revision] += 1
        if any(p in path for p in STUDENT_ENDPOINTS):
            student_hits += 1
        if current and revision == current:
            live_entries.append((status, path))

    print(f"UMP error watch - {SERVICE} - last {args.hours:g} h")
    print(f"  since {since_iso}")
    if current:
        print(f"  serving revision: {current}")
    if not entries:
        print("  ✓ no 5xx at all")
        return 0

    if current:
        if not live_entries:
            print(f"  ✓ no 5xx on the revision that is serving traffic right now")
            print(f"    ({len(entries)} older 5xx in the window, already fixed)")
            return 0
        print(f"  ✗ {len(live_entries)} 5xx on the CURRENT revision:")
        for (status, path), count in Counter(live_entries).most_common(20):
            flag = "  ← STUDENT-FACING" if any(p in path for p in STUDENT_ENDPOINTS) else ""
            print(f"    {status}  {path}  x{count}{flag}")
        live_student = sum(1 for _s, p in live_entries
                           if any(x in p for x in STUDENT_ENDPOINTS))
        if live_student:
            print(f"\n  ✗ {live_student} student-facing failures — students are seeing errors")
            return 1
        return 0

    print(f"  {len(entries)} 5xx responses (current revision unknown)")
    for (status, path), count in by_endpoint.most_common(20):
        flag = "  ← STUDENT-FACING" if any(p in path for p in STUDENT_ENDPOINTS) else ""
        print(f"    {status}  {path}  x{count}{flag}")
    if student_hits:
        print(f"\n  ✗ {student_hits} student-facing failures")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
