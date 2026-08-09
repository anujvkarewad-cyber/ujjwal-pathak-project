// Single entry point for all API calls. Switches between local mock and
// Google Apps Script based on the REACT_APP_APPS_SCRIPT_URL env variable.
//
// TRANSPORT:
//   • Local dev / no URL       → src/api/local-adapter.js (mock)
//   • Google Apps Script (all) → JSONP <script> tag (bypasses CORS entirely)
//
// Why JSONP? Apps Script Web Apps return a 302 redirect that trips CORS
// intermittently in browsers (ERR_ABORTED). JSONP loads via a plain <script>
// tag which is exempt from CORS, so calls work 100% of the time. The URL
// length limit (~2KB) is comfortably above any payload the dashboard sends.
//
// LARGE PAYLOADS (file uploads): Apps Script's POST handling is noticeably
// less reliable than its GET/JSONP handling once the body grows past a few
// hundred KB — the browser-to-script.googleusercontent.com hand-off that
// Apps Script does internally on every POST is more likely to drop the
// connection mid-transfer as the body gets bigger. There's no hard
// documented ceiling; it's a reliability curve, not a wall. So large files
// are uploaded in small chunks (see api/notes.js: createNoteChunked) —
// each chunk is small enough to be reliable on its own, and apiCallWithRetry
// below gives every chunk a couple of automatic retries to absorb any
// residual flakiness.

import { APPS_SCRIPT_URL, USE_MOCK, MOCK_DELAY_MS } from './config';
import { handle as mockHandle } from './local-adapter';

const wait = (ms) => new Promise(r => setTimeout(r, ms));
let jsonpCounter = 0;

function jsonpCall(action, payload) {
  return new Promise((resolve, reject) => {
    const cb = 'upmCb_' + Date.now().toString(36) + '_' + (++jsonpCounter);
    const script = document.createElement('script');

    const cleanup = () => {
      try { delete window[cb]; } catch (_) { window[cb] = undefined; }
      if (script.parentNode) script.parentNode.removeChild(script);
      clearTimeout(timer);
    };

    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`API ${action} timed out`));
    }, 30000);

    window[cb] = (data) => {
      cleanup();
      if (data && data.error) return reject(new Error(data.error));
      resolve(data && data.result !== undefined ? data.result : data);
    };

    const url = new URL(APPS_SCRIPT_URL);
    url.searchParams.set('action', action);
    url.searchParams.set('callback', cb);
    if (payload && Object.keys(payload).length) {
      url.searchParams.set('payload', JSON.stringify(payload));
    }
    // Cache buster so browsers don't reuse stale JS responses.
    url.searchParams.set('_', String(Date.now()));

    script.src = url.toString();
    script.async = true;
    script.onerror = () => {
      cleanup();
      reject(new Error(`API ${action} failed to load`));
    };
    document.head.appendChild(script);
  });
}

export async function apiCall(action, payload = {}) {
  if (USE_MOCK) {
    if (MOCK_DELAY_MS > 0) await wait(MOCK_DELAY_MS);
    return mockHandle(action, payload);
  }
  return jsonpCall(action, payload);
}

// For payloads too large for a JSONP query string (e.g. base64 PDF uploads).
// Sent as a plain-text POST body so the browser treats it as a "simple
// request" and skips the CORS preflight (which Apps Script doesn't handle).
function postCall(action, payload) {
  return fetch(APPS_SCRIPT_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify({ action, payload }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data && data.error) throw new Error(data.error);
      return data && data.result !== undefined ? data.result : data;
    });
}

export async function apiCallLarge(action, payload = {}) {
  if (USE_MOCK) {
    if (MOCK_DELAY_MS > 0) await wait(MOCK_DELAY_MS);
    return mockHandle(action, payload);
  }
  return postCall(action, payload);
}

// POST with real upload-progress + speed tracking (XHR gives byte-level
// progress events; fetch() does not expose upload progress reliably).
// onProgress is called as onProgress({ loaded, total, percent, speedBps }).
//
// NOTE: kept for callers that still want a single-shot upload with native
// XHR progress (e.g. small, non-PDF payloads). For PDF notes, prefer the
// chunked path in api/notes.js — see the transport note at the top of this
// file for why single large POSTs to Apps Script aren't reliable.
function postCallWithProgress(action, payload, onProgress) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ action, payload });
    const xhr = new XMLHttpRequest();
    xhr.open('POST', APPS_SCRIPT_URL, true);
    xhr.setRequestHeader('Content-Type', 'text/plain;charset=utf-8');

    let lastLoaded = 0;
    let lastTime = Date.now();

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable || !onProgress) return;
      const now = Date.now();
      const elapsedSec = (now - lastTime) / 1000;
      const deltaBytes = e.loaded - lastLoaded;
      // Smoothed instantaneous speed; skip near-zero intervals to avoid spikes.
      const speedBps = elapsedSec > 0.15 ? deltaBytes / elapsedSec : null;
      if (speedBps !== null) {
        lastLoaded = e.loaded;
        lastTime = now;
      }
      onProgress({
        loaded: e.loaded,
        total: e.total,
        percent: Math.round((e.loaded / e.total) * 100),
        speedBps: speedBps,
      });
    };

    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (data && data.error) { reject(new Error(data.error)); return; }
        resolve(data && data.result !== undefined ? data.result : data);
      } catch (err) {
        reject(err);
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.send(body);
  });
}

export async function apiCallLargeWithProgress(action, payload = {}, onProgress) {
  if (USE_MOCK) {
    if (onProgress) {
      // Fake a smooth progress bar in mock/dev mode.
      const total = (payload.fileData || '').length || 100000;
      for (let p = 0; p <= 100; p += 20) {
        onProgress({ loaded: (p / 100) * total, total, percent: p, speedBps: 900000 });
        await wait(80);
      }
    }
    return mockHandle(action, payload);
  }
  return postCallWithProgress(action, payload, onProgress);
}

// Retries a request-making function a few times with exponential backoff.
// Used for chunked uploads: each chunk is small and should almost always
// succeed on the first try, but this absorbs the occasional transient
// Apps Script POST failure without surfacing it to the user.
//
// fn: () => Promise<T>  — must create a *new* request each call (don't
//     pass an already-started promise)
// attempts: total tries including the first (default 3)
// baseDelayMs: delay before the 2nd try; doubles each subsequent retry
//     (e.g. 600 → 600ms, 1200ms, 2400ms, ...)
export async function apiCallWithRetry(fn, attempts = 3, baseDelayMs = 600) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (i < attempts - 1) {
        await wait(baseDelayMs * Math.pow(2, i));
      }
    }
  }
  throw lastErr;
}
