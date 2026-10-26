import { apiCall, apiUrl, getToken } from './backendClient';

// Multipart upload — apiCall is JSON-only, so the photo goes through fetch.
export async function parseTargetPlanPhoto(file) {
  const form = new FormData();
  form.append('file', file);
  const token = getToken();
  const res = await fetch(apiUrl('/api/target-plans/parse-photo'), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
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

export const fetchTargetPlans = () => apiCall('/api/target-plans');

export const publishTargetPlan = (body) =>
  apiCall('/api/target-plans', { method: 'POST', body });

export const editTargetPlanDay = (planId, body) =>
  apiCall(`/api/target-plans/${encodeURIComponent(planId)}/day`, { method: 'PATCH', body });

export const cancelTargetPlan = (planId) =>
  apiCall(`/api/target-plans/${encodeURIComponent(planId)}/cancel`, { method: 'POST' });

export const previewPersonalTargetAudience = (body) => apiCall('/api/smart-targets/mentor/audience', { method: 'POST', body });
