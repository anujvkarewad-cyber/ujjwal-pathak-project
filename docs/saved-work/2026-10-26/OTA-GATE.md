# Existing installed-app OTA release gate

Read-only local check, 26 October 2026 (IST).

- `mobile/ota-baselines.json` has `preview: null` and `production: null`.
- Executed the actual `assertApprovedRuntime` policy against this ledger for both channels. Both refuse publication: `No device-validated OTA baseline recorded for this channel. Publishing is blocked.`
- This proves the local release ledger lacks approved baseline evidence. It does **not** prove OTA is disabled in the owner's installed app.
- Do not populate deviceValidated, project/runtime/signing/APK hashes from guesses or synthetic fixture-runtime inspection. Recover genuine installed/build evidence and validate it first.
- No ledger/config/flag/signing change, publication or activation performed.

Latest completed local batch remains: root backend 591 PASS; candidate workbook 87 PASS; prototype 91 PASS; isolated Targets 42 PASS; mobile 411 PASS; student web 333 PASS; workflows 21 PASS; actual mentor authoring 35 PASS per tree. See STATUS.md and retained logs.

Release remains HOLD for the OTA baseline mapping plus authenticated live Targets/sync/progress, recovery, real academic content approval, private access, device/capacity and ranking/rollout gates listed in STATUS.md. This is not an all-set-to-push certification.
