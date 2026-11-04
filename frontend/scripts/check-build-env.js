#!/usr/bin/env node
// Build guard — runs automatically before `npm run build` (package.json "prebuild").
//
// The mentor app talks to the Google Apps Script for the roster and student
// profiles. If REACT_APP_APPS_SCRIPT_URL is missing at build time, CRA compiles
// the app with an empty URL and api/config.js silently switches USE_MOCK on:
// every Apps Script call is then answered by the local mock adapter. The app
// still loads, so the failure is invisible until someone opens a page that needs
// real data (this is exactly how student profiles broke on 4 Nov 2026).
//
// A build without the URL is therefore refused here instead of shipping silently.
const url = (process.env.REACT_APP_APPS_SCRIPT_URL || '').trim();

const fail = (message) => {
  console.error('\n✗ Build blocked: ' + message);
  console.error('  Fix: set REACT_APP_APPS_SCRIPT_URL in frontend/.env.production');
  console.error('  (the Apps Script /exec URL; it is public and already in every shipped bundle)\n');
  process.exit(1);
};

if (!url) fail('REACT_APP_APPS_SCRIPT_URL is empty — the app would fall back to mock data.');
if (!/^https:\/\/script\.google\.com\/macros\/s\/[A-Za-z0-9_-]+\/exec$/.test(url)) {
  fail(`REACT_APP_APPS_SCRIPT_URL is not an Apps Script /exec URL: ${url}`);
}
const apiBase = (process.env.REACT_APP_MENTOR_API_URL || 'same-origin').trim();
if (/localhost|127\.0\.0\.1/i.test(apiBase)) {
  fail(`REACT_APP_MENTOR_API_URL points at ${apiBase}; the browser cannot reach it in the cloud.`);
}
console.log(`✓ build env ok — Apps Script ${url.slice(0, 58)}…, API ${apiBase}`);
