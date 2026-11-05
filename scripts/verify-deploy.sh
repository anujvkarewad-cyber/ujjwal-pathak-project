#!/usr/bin/env bash
# Post-deploy smoke test. Runs against the LIVE service and exits non-zero if
# anything the mentor app depends on is missing. Run this after EVERY deploy:
#
#     ./scripts/verify-deploy.sh                 # default service
#     ./scripts/verify-deploy.sh https://host    # any URL
#
# It answers the two questions that cost us a day:
#   1. did the SPA build with the Apps Script URL (not the mock adapter)?
#   2. is the backend endpoint set the app calls actually deployed?
set -uo pipefail

URL="${1:-https://ujjwal-pathak-app-566076646952.asia-south1.run.app}"
fail=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }

echo "verify-deploy: $URL"

# 1. health
health=$(curl -fsS --max-time 30 "$URL/api/health" 2>/dev/null) || health=""
if [[ "$health" == *'"ok":true'* ]]; then ok "health: $health"; else bad "health endpoint failed: ${health:-no response}"; fi

# 2. the served bundle
bundle=$(curl -fsS --max-time 60 "$URL/" | grep -o '/static/js/main\.[a-z0-9]*\.js' | head -1)
if [[ -z "$bundle" ]]; then
  bad "index.html did not reference a main bundle"
else
  js=$(curl -fsS --max-time 120 "$URL$bundle")
  size=$(printf '%s' "$js" | wc -c | tr -d ' ')
  ok "bundle $bundle ($size bytes)"

  # 2a. Apps Script URL baked in — without it the app silently runs on mock data
  if [[ "$js" == *"script.google.com/macros/s/"*"/exec"* ]]; then
    ok "Apps Script URL is baked in (real roster/profile data)"
  else
    bad "Apps Script URL MISSING from the bundle — every apiCall page would show mock data"
  fi

  # 2b. endpoints the mentor flow needs
  for marker in "/api/mentor-workspace/send" "/api/notes-inbox" "/api/messages/reply"; do
    if [[ "$js" == *"$marker"* ]]; then ok "bundle calls $marker"; else bad "bundle never calls $marker"; fi
  done

  # 2c. the one-tap send button label (proves the direct-send build)
  if [[ "$js" == *"Send now"* ]]; then ok "one-tap send UI present"; else bad "one-tap send UI missing"; fi

  # 2d. the removed review detour must be gone
  if [[ "$js" == *"Review reply"* ]]; then bad "old 'Review reply' detour is still in the bundle"; else ok "old 'Review reply' detour removed"; fi

  # 2e. per-student access switch in Daily tracker · Dates (the data-testid prefix
  # survives minification, so this is proof the SPA was built from current source)
  if [[ "$js" == *"access-toggle-"* ]]; then ok "per-student access switch shipped"; else bad "per-student access switch MISSING — an older SPA is still being served"; fi
  # 2g. student start-day progress & timeline UI in Target Plans
  if [[ "$js" == *"start-day-progress"* && "$js" == *"start-day-timeline"* ]]; then ok "student start-day progress & timeline UI present"; else bad "student start-day progress & timeline UI MISSING from bundle"; fi
  # 2f. advisory only: the old batch-wide pill must not come back
  if [[ "$js" == *"ON/OFF"* ]]; then echo "  ! advisory: a batch-wide 'ON/OFF' control appears in this bundle — confirm it is not the removed batch access switch"; fi
fi

# 3. backend surface — openapi.json is the authoritative route list
spec=$(curl -fsS --max-time 30 "$URL/openapi.json" 2>/dev/null) || spec=""
if [[ -z "$spec" ]]; then
  bad "openapi.json unavailable"
else
  for path in /api/mentor-workspace/send /api/mentor-workspace/review /api/notes-inbox \
              /api/notes-inbox/skip /api/notes-inbox/unskip /api/messages/send /api/messages/reply /api/student-targets/all-progress; do
    if printf '%s' "$spec" | grep -q "\"$path\""; then ok "route $path deployed"; else bad "route $path NOT deployed"; fi
  done
  # every protected route must demand a token (401 without one)
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST -H 'Content-Type: application/json' -d '{}' "$URL/api/mentor-workspace/send")
  if [[ "$code" == "401" || "$code" == "403" ]]; then ok "protected routes demand a token ($code)"; else bad "send route answered $code without a token"; fi
fi

# 4. SPA deep links must serve the app (not a 404) — students/profiles open by URL
for path in "/" "/students" "/students/UMP0011" "/batches" "/target-plans" "/messages" "/notes-inbox"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$URL$path")
  if [[ "$code" == "200" ]]; then ok "page $path ($code)"; else bad "page $path returned $code"; fi
done

if [[ $fail -ne 0 ]]; then
  echo
  echo "DEPLOY FAILED VERIFICATION — do not hand this over. Fix, redeploy, run again."
  exit 1
fi
echo
echo "All checks passed."
