# Mobile sync files — for student-dashboard-frontend

These are the changed files needed to make MCQ progress appear on the mentor
analytics dashboard (Analytics → All Students Overview) and to fix the
notification "Clear All" crash.

Copy each file into your `student-dashboard-frontend` clone as follows:

| In this repo (`mobile-files/`)               | Copy to (in student repo)                     |
|----------------------------------------------|-----------------------------------------------|
| `mobile/App.tsx`                             | `mobile/App.tsx`                              |
| `mobile/env.example`                         | `mobile/env.example`                          |
| `mobile/package-lock.json`                   | `mobile/package-lock.json`                    |
| `mobile/src/config/config.ts`                | `mobile/src/config.ts`                        |
| `mobile/src/context/ProgressSyncContext.tsx` | `mobile/src/context/ProgressSyncContext.tsx`  |
| `mobile/src/services/hmacSha256.ts`          | `mobile/src/services/hmacSha256.ts`           |
| `mobile/src/services/progressSync.ts`        | `mobile/src/services/progressSync.ts`         |
| `mobile/src/screens/NotificationsScreen.tsx` | `mobile/src/screens/NotificationsScreen.tsx`  |
| `mobile/src/screens/ProfileScreen.tsx`       | `mobile/src/screens/ProfileScreen.tsx`        |

Note: `src/config/config.ts` maps to `mobile/src/config.ts` (single file, not a
`config/` folder) in the student repo.

## What these changes do

- **progressSync.ts** — POST `/api/consent` and `/api/progress-sync` with
  allowlisted per-chapter summaries + weekly trend (raw answers never leave the
  device).
- **hmacSha256.ts** — pure-TS HMAC-SHA256 for the `X-Sync-Token` header.
- **ProgressSyncContext.tsx** — restores the saved sharing choice, exposes
  `setSharing()` + `syncNow()`, auto-syncs after a completed attempt while
  sharing is ON.
- **ProfileScreen.tsx** — "Share MCQ progress with mentor" toggle (shown only
  in Full-live mode).
- **NotificationsScreen.tsx** — replaced the web-only global `confirm()` (which
  crashed on Android) with a native `Alert`.
- **config.ts / env.example** — added `EXPO_PUBLIC_MENTOR_SYNC_SECRET` and
  `EXPO_PUBLIC_APP_VERSION`.
- **App.tsx** — registered the `ProgressSyncProvider`.

## After copying

```powershell
cd student-dashboard-frontend
git add -A
git commit -m "Sync MCQ progress to mentor analytics + fix notification crash"
git push
```

Then build a new APK (EAS) and deploy.

## OTA updates (no more APK rebuild for small changes)

This project now uses Expo EAS Update (expo-updates). After you push this
version and build ONE new APK with expo-updates embedded, all future
JS/UI/logic changes go to installed apps via `eas update` — no new APK needed.

Setup (one time, on your machine):
```
cd mobile
npx eas-cli login          # your Expo account (one time)
npx eas-cli build --platform android --profile apk   # one APK with expo-updates
```

Push small changes WITHOUT a new APK:
```
cd mobile
npx eas-cli update --channel production --message "describe change"
```
Students' installed apps auto-download the new bundle on next open (or via
`update.` reload). Only NATIVE changes (new native module, permissions,
adding a native dependency) still require an APK build.
