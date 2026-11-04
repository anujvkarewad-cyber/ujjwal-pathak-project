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


def run_gcloud(args: list[str]) -> str:
    cmd = ["gcloud", "logging", "read"] + args + [
        "--project=" + PROJECT, "--format=json", "--limit=2000"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gcloud logging read failed")
    return out.stdout


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
    raw = run_gcloud([filt])
    try:
        entries = json.loads(raw or "[]")
    except json.JSONDecodeError:
        print("could not read the logs", file=sys.stderr)
        return 0

    by_endpoint = Counter()
    by_status = Counter()
    student_hits = 0
    for entry in entries:
        req = entry.get("httpRequest") or {}
        status = req.get("status")
        url = req.get("requestUrl") or ""
        path = url.split("?")[0]
        by_endpoint[(status, path)] += 1
        by_status[status] += 1
        if any(p in path for p in STUDENT_ENDPOINTS):
            student_hits += 1

    print(f"UMP error watch - {SERVICE} - last {args.hours:g} h")
    print(f"  since {since_iso}")
    if not entries:
        print("  ✓ no 5xx at all")
        return 0

    print(f"  {len(entries)} 5xx responses")
    for (status, path), count in by_endpoint.most_common(20):
        flag = "  ← STUDENT-FACING" if any(p in path for p in STUDENT_ENDPOINTS) else ""
        print(f"    {status}  {path}  x{count}{flag}")
    if student_hits:
        print(f"\n  ✗ {student_hits} student-facing failures — students are seeing errors")
        return 1
    print("\n  ⚠ 5xx seen, but none on a student endpoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
