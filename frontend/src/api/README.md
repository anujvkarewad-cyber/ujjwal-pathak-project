# API Layer — replaceable adapter for Google Apps Script

All UI components consume data **only** through hooks in `hooks.js` (react-query wrappers)
around plain async functions in `students.js`, `dashboard.js`, etc.

Every function calls `apiCall(action, payload)` from `client.js`. That single function is the
**one place** you swap when moving to a real backend.

## Local mode (default)
`REACT_APP_APPS_SCRIPT_URL` is empty → `client.js` routes to `local-adapter.js`, which serves
data from `src/data/*.js` with a small artificial delay so loading states are exercised.

## Google Apps Script mode
1. Deploy an Apps Script Web App (`doPost(e)`) that:
   - Reads `JSON.parse(e.postData.contents)` → `{ action, payload }`
   - Switches on `action` and returns
     `ContentService.createTextOutput(JSON.stringify({ result })).setMimeType(ContentService.MimeType.JSON)`
   - Returns `{ error: '<message>' }` on failure.
2. Add to `/app/frontend/.env`:
   ```
   REACT_APP_APPS_SCRIPT_URL=https://script.google.com/macros/s/AKf.../exec
   ```
3. Restart the frontend. No component/page code needs to change.

## Actions the Apps Script must implement
Same names and payload shapes as in `local-adapter.js`:

| Action | Payload | Returns |
| --- | --- | --- |
| `students.list` | – | `{ students: [...], options: { batchOptions, attemptOptions, groupOptions, statusOptions } }` |
| `students.get` | `{ id }` | Student object or `null` |
| `students.addNote` | `{ id, note }` | `{ ok: true, notes: [...] }` |
| `dashboard.kpis` | – | `{ total, active, atRisk, pending, avgHours, avgAttendance, avgMcq, weeklySub }` |
| `dashboard.recentActivity` | – | `[{ id, type, student, action, time }]` |
| `dashboard.weeklyStudy` | – | `[{ day, hours, target }]` |
| `dashboard.attendanceTrend` | – | `[{ week, attendance }]` |
| `dashboard.performanceMix` | – | `[{ name, value, color }]` |
| `dashboard.batchOverview` | – | `[{ name, students, attendance, mcq }]` |
| `dashboard.upcomingTasks` | – | `[{ id, title, due, priority }]` |
| `tracker.day` | `{ dayIndex, batch }` | `{ list, submitted, missed, rate, days }` |
| `leaderboard.list` | `{ mode }` | `[Student with score, ...]` |
| `announcements.list` | – | `[Announcement]` |
| `announcements.create` | `{ title, body, audience }` | New announcement |
| `announcements.togglePin` | `{ id }` | `{ ok: true }` |
| `reports.batch` | – | `[{ name, students, attendance, mcq }]` |
| `reports.students` | – | `[{ id, name, avatar, batch, attendance, studyHours, mcqAccuracy, submissionRate }]` |
| `mentor.get` | – | `{ name, email, avatar }` |
| `mentor.update` | `{ name?, email? }` | Updated mentor |
| `notifications.get` | – | `{ emailNotif, smsNotif, dailyDigest }` |
| `notifications.update` | partial | Updated settings |
