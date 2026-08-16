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
// Without this guard the raw failure surfaced to users as:
//   Unexpected token '<', "<!doctype "... is not valid JSON
// which says nothing about *why* HTML came back. The usual causes are a
// mistyped/unregistered API path falling through to the SPA catch-all, or the
// dev server proxy not forwarding /api to the FastAPI backend.
async function parseJson(res, url) {
  const contentType = res.headers.get('content-type') || '';
  const text = await res.text();

  if (!contentType.includes('json')) {
    const looksLikeHtml = /^\s*<(?:!doctype|html)/i.test(text);
    const err = new Error(
      looksLikeHtml
        ? `Expected JSON from ${url} but received an HTML page (HTTP ${res.status}). ` +
          'The request did not reach the API — check that the path is a real API route ' +
          'and that the dev server proxies /api to the backend.'
        : `Expected JSON from ${url} but received "${contentType || 'unknown content type'}" (HTTP ${res.status}).`
    );
    err.status = res.status;
    err.contentType = contentType;
    err.bodyPreview = text.slice(0, 200);
    throw err;
  }

  if (!text) return null; // 204 / empty body

  try {
    return JSON.parse(text);
  } catch (cause) {
    const err = new Error(`Malformed JSON received from ${url}: ${cause.message}`);
    err.status = res.status;
    err.bodyPreview = text.slice(0, 200);
    throw err;
  }
}
