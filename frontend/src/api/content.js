// AI Content review API functions (mentor-only).
import { apiCall, USE_MOCK } from './backendClient';
import { mockContent } from './local-content';

const call = (path, opts) => (USE_MOCK ? mockContent(path, opts) : apiCall(path, opts));

export const loginMentor = (email, password) =>
  USE_MOCK ? Promise.resolve({ token: 'mock-token', email, role: 'mentor' }) : apiCall('/api/auth/login', { method: 'POST', body: { email, password } });

export const contentStats = () => call('/api/content/stats');
export const listQueue = (params) => call('/api/content/queue', { params });
export const getQuestion = (id) => call(`/api/content/questions/${id}`);
export const updateQuestion = (id, patch) => call(`/api/content/questions/${id}`, { method: 'PUT', body: patch });
export const decideQuestion = (id, body) => call(`/api/content/questions/${id}/decision`, { method: 'POST', body });
export const getScenario = (id) => call(`/api/content/scenarios/${id}`);
export const decideScenario = (id, body) => call(`/api/content/scenarios/${id}/decision`, { method: 'POST', body });
export const listChapters = (params) => call('/api/content/chapters', { params });
export const getChapterGate = (id) => call(`/api/content/chapters/${id}/gate`);
export const approveChapter = (id) => call(`/api/content/chapters/${id}/approve`, { method: 'POST', body: {} });
export const listReleases = (params) => call('/api/content/releases', { params });
export const getRelease = (rev) => call(`/api/content/releases/${rev}`);
export const listAudit = (params) => call('/api/content/audit', { params });
export const validationDetail = (id) => call(`/api/content/validation/${id}`);
