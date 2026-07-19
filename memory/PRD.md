# Ujjwal Pathak Mentorship — Mentor Dashboard

## Problem Statement
Modern, premium Mentor Dashboard for a CA mentorship platform (CA Foundation / Intermediate / Final). Frontend-only (React + Tailwind + Recharts + Lucide). Dummy JSON data, ready to be swapped with a Google Apps Script + Google Sheets backend later. No auth, no DB, no server dependencies.

## Branding
- Primary: `#2563EB` · Secondary: `#1E40AF` · Background: `#F8FAFC`
- Fonts: Manrope (headings), IBM Plex Sans (body)
- Theme: Modern premium SaaS dashboard, rounded soft-shadow cards
- Dark mode: fully functional, persisted via `localStorage`

## Architecture
```
frontend/src/
├── App.js                      # React Router setup
├── index.css                   # Tailwind + fonts + design tokens
├── layouts/DashboardLayout.jsx # Sidebar + Topbar shell
├── components/
│   ├── layout/                 # Sidebar, Topbar
│   ├── dashboard/              # KPICard, RecentActivity, UpcomingTasks
│   ├── students/               # StudentTable (search, filters, pagination)
│   ├── charts/                 # All Recharts wrappers
│   └── common/                 # RiskBadge, StatusBadge
├── pages/                      # Dashboard, Students, StudentProfile,
│                               # DailyTracker, Leaderboard, Announcements,
│                               # Reports, Settings
├── hooks/useTheme.js           # useSyncExternalStore shared theme
├── utils/format.js             # cn, initials, colors
└── data/                       # students.js (50 deterministic students),
                                # dashboard.js, announcements.js
```

## Data Source Contract (for later Google Apps Script swap)
All data comes from `src/data/*.js` as plain exports. Swap each named export for a `fetch()` call to Apps Script — same shape.

- `students` — array of 50 student objects (id, name, batch, attempt, group, level, attendance %, studyHours, mcqAccuracy, submissionRate, risk, status, weekly[7], monthly[4], tracker[14], mentorNotes[])
- `kpis()` — aggregated dashboard KPIs
- `announcements` — array of announcement objects
- Batches: **Super 30, Super 11, Last 15 Days, Last 40 Days** · Attempt: **Sept 2026**

## What's Implemented (Feb 19, 2026)
- Dashboard: 8 KPI cards (total, active, pending, at-risk, avg hours, attendance, MCQ, submission), attendance area chart, performance donut, weekly study bars, batch overview bars, recent activity, upcoming tasks
- Students: table with avatars, search, 4 filter dropdowns (batch/attempt/group/status), pagination, risk & status badges, attendance progress bars, view action
- Student Profile: personal info card, 4 stat cards, weekly line chart, monthly bar chart, performance radar, mentor notes, 14-day tracker heatmap
- Daily Tracker: date-scoped submission tracker, per-batch filter, day switcher, per-student hours/MCQ table
- Leaderboard: overall/weekly/monthly ranking tabs, 3-podium top performers, top 20 table
- Announcements: create form, pin/unpin, pinned + history sections
- Reports: batch and student report tabs, KPI comparison chart, Export button (UI only)
- Settings: mentor profile form, dark-mode toggle, notification switches (email/SMS/daily digest)
- Fully responsive (mobile drawer sidebar via topbar hamburger)
- Dark mode with cross-component sync (useSyncExternalStore) + persistence

## Test Results
Testing agent — iteration 1: **98% pass (46/47)**. Sole low-priority issue (topbar theme-toggle instance sync) was fixed post-report and verified via Playwright screenshot script.

## Next Action Items (P1 — deferred)
1. Wire each `data/*.js` export to a Google Apps Script endpoint (single `fetch` per file).
2. Add CSV / PDF export logic behind the Export button in Reports.
3. Add Add-Note dialog wiring (currently button placeholder on Student Profile).
4. Command palette (⌘K) — kbd hint already in Topbar search.
5. Filter combinations persistence via URL query params.

## Next Action Items (P2)
- Per-student comparison view
- Bulk actions on student table (assign group, send message)
- Announcement scheduling
