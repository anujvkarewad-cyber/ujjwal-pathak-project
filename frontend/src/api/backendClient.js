// FastAPI mentor backend client (NEW AI Content + Analytics APIs).
// Separate from the existing Apps Script client (client.js) — existing pages
// keep using their current transport untouched.
//
// Base URL: REACT_APP_MENTOR_API_URL. When empty, calls route to the local
// mock adapter (local-content.js), consistent with the existing mock pattern.

const RAW_BASE_URL = (process.env.REACT_APP_MENTOR_API_URL || '').trim();
// ''                        → mock adapter (no backend configured)
// 'same-origin' | 'proxy' | '/' → same-origin backend (dev-server proxy or the
//                             FastAPI static deployment) — used in Codespaces,
//                             where the browser cannot reach localhost:8010
// 'http(s)://…'             → absolute backend URL (e.g. http://localhost:8010)
const SAME_ORIGIN = ['same-origin', 'proxy', '/'].includes(RAW_BASE_URL.toLowerCase());
const BASE_URL = SAME_ORIGIN ? '' : RAW_BASE_URL.replace(/\/$/, '');
export const USE_MOCK = !RAW_BASE_URL;
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
  return res.json();
}
