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
