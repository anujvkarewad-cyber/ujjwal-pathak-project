// FastAPI mentor backend client (NEW AI Content + Analytics APIs).
// Separate from the existing Apps Script client (client.js) — existing pages
// keep using their current transport untouched.
//
// Base URL: REACT_APP_MENTOR_API_URL. When empty the client defaults to
// same-origin and always talks to the live backend — there is no mock
// fallback, so the dashboard can never show DEMO content.

const RAW_BASE_URL = (process.env.REACT_APP_MENTOR_API_URL || 'same-origin').trim();
// 'same-origin' | 'proxy' | '/' → same-origin backend (dev-server proxy or the
//                             FastAPI static deployment) — used in Codespaces,
//                             where the browser cannot reach localhost:8010
// 'http(s)://…'             → absolute backend URL (e.g. http://localhost:8010)
// The mock adapter has been REMOVED from the data path: when the env var is
// empty the client defaults to same-origin, so the live API is always hit and
// the dashboard can never fall back to DEMO content.
const SAME_ORIGIN = ['same-origin', 'proxy', '/'].includes(RAW_BASE_URL.toLowerCase());
const BASE_URL = SAME_ORIGIN ? '' : RAW_BASE_URL.replace(/\/$/, '');
export const USE_MOCK = false;
export const RELATIVE_BASE = SAME_ORIGIN || BASE_URL.startsWith('/');

export const AUTH_EVENT = 'upm:auth-required';
const TOKEN_KEY = 'upm_mentor_token';

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
};
export const setToken = (t) => {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
};

export async function apiCall(path, { method = 'GET', body = null, params = null } = {}) {
  let url = `${BASE_URL}${path}`;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  const token = getToken();
  const res = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EVENT));
    throw new Error('Authentication required');
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail || j);
    } catch {
      /* keep default */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return parseJson(res, url);
}

// Reads the body as JSON, but fails with a diagnosable message when the server
// answered with something else (almost always the SPA's index.html).
//
// FIXED: More robust handling to prevent the "Expected JSON but received HTML" banner
// - Detects proxy failure (HTML) and provides actionable guidance
// - Backend now returns JSON 502 on proxy error instead of HTML (craco.config.js fix)
// - Backend SPA fallback never serves HTML for /api/* (server.py fix)
// - Adds fallback attempt to detect backend unavailability

function isHtml(text) {
  return /^\s*<(?:!doctype|html)/i.test(text);
}

async function parseJson(res, url) {
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  const text = await res.text();

  // If server returned HTML with 200 — it means request hit SPA, not API.
  // This happens when:
  // 1. Dev server proxy not working (backend not running)
  // 2. API route typo
  // 3. REACT_APP_MENTOR_API_URL misconfigured in cloud preview
  if (!contentType.includes('json') || isHtml(text)) {
    const looksLikeHtml = isHtml(text) || contentType.includes('text/html');
    
    // Enhanced error message with specific fix instructions
    let message;
    if (looksLikeHtml) {
      const isQueue = url.includes('/api/content/queue');
      const isSameOrigin = !BASE_URL || BASE_URL === '';
      
      if (isSameOrigin) {
        // Same-origin means we're using CRA proxy
        message = `Backend not reachable for ${url}. ` +
          (isQueue 
            ? 'The Review Queue API did not respond. ' 
            : '') +
          'Fix: Ensure backend is running:\n' +
          '1. Open a new terminal\n' +
          '2. Run: ./run-backend.sh (should start on http://localhost:8010)\n' +
          '3. Check: curl http://localhost:8010/api/content/queue?limit=1\n' +
          'If backend IS running, check craco.config.js proxy target (MENTOR_API_PROXY_TARGET).\n' +
          `Received HTML instead of JSON (HTTP ${res.status}) — dev server returned index.html.`;
      } else {
        message = `Expected JSON from ${url} but received an HTML page (HTTP ${res.status}). ` +
          `API base is set to ${BASE_URL}. ` +
          'In cloud previews (Codespaces, E2B, Gitpod), use REACT_APP_MENTOR_API_URL=same-origin ' +
          'so the dev server proxies /api to the backend. ' +
          'Direct localhost:8010 does NOT work from browser in cloud.';
      }
    } else {
      message = `Expected JSON from ${url} but received "${contentType || 'unknown content type'}" (HTTP ${res.status}).`;
    }

    const err = new Error(message);
    err.status = res.status;
    err.contentType = contentType;
    err.bodyPreview = text.slice(0, 300);
    err.isHtmlError = looksLikeHtml;
    throw err;
  }

  if (!text) return null; // 204 / empty body

  try {
    return JSON.parse(text);
  } catch (cause) {
    const err = new Error(`Malformed JSON received from ${url}: ${cause.message}`);
    err.status = res.status;
    err.bodyPreview = text.slice(0, 300);
    throw err;
  }
}
