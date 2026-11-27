// Live-quiz selection API (mentor-only). Read-only on purpose: this tab shows what the student
// app will serve, it never writes. Same `apiCall` path as api/content.js — not the Apps Script
// client in api/client.js, which cannot reach these routes.
import { apiCall } from './backendClient';

const call = (path, opts) => apiCall(path, opts);

export const getLiveQuizPool = () => call('/api/live-quiz-admin/pool');

export const previewLiveQuiz = (body) =>
  call('/api/live-quiz-admin/preview', { method: 'POST', body });
