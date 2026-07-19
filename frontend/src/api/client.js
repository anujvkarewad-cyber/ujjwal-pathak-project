// Single entry point for all API calls. Switches between local mock and
// Google Apps Script based on the REACT_APP_APPS_SCRIPT_URL env variable.
//
// When you deploy your Apps Script Web App, your `doPost(e)` should:
//   1. Parse JSON from `e.postData.contents` → `{ action, payload }`
//   2. Route on `action` and return `ContentService.createTextOutput(
//        JSON.stringify({ result: <same shape as local-adapter> })
//      ).setMimeType(ContentService.MimeType.JSON)`
//   3. On errors, return `{ error: '<message>' }`.

import { APPS_SCRIPT_URL, USE_MOCK, MOCK_DELAY_MS } from './config';
import { handle as mockHandle } from './local-adapter';

const wait = (ms) => new Promise(r => setTimeout(r, ms));

export async function apiCall(action, payload = {}) {
  if (USE_MOCK) {
    if (MOCK_DELAY_MS > 0) await wait(MOCK_DELAY_MS);
    return mockHandle(action, payload);
  }
  // Real Google Apps Script call.
  // Note: text/plain content-type avoids CORS preflight for Apps Script.
  const res = await fetch(APPS_SCRIPT_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify({ action, payload }),
  });
  if (!res.ok) throw new Error(`API ${action} failed with status ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data.result ?? data;
}
