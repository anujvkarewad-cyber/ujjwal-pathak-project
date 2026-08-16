// Mentor analytics API functions (mentor-only, consented summaries only).
//
// These always hit the live FastAPI backend through `apiCall`. The DEMO/mock
// adapter has been removed from this path.
import { apiCall } from './backendClient';

const call = (path, opts) => apiCall(path, opts);

export const analyticsOverview = () => call('/api/analytics/overview');
export const studentsList = () => call('/api/analytics/students');
export const studentAnalysis = (id) => call(`/api/analytics/students/${id}`);
export const heatmap = (params) => call('/api/analytics/heatmap', { params });
export const weakChapters = (params) => call('/api/analytics/weak-chapters', { params });
export const groupAnalysis = () => call('/api/analytics/groups');
export const atRisk = () => call('/api/analytics/at-risk');
export const improvement = () => call('/api/analytics/improvement');
export const inactiveStudents = (params) => call('/api/analytics/inactive', { params });
export const listFollowups = (params) => call('/api/analytics/followups', { params });
export const createFollowup = (body) => call('/api/analytics/followups', { method: 'POST', body });
export const updateFollowup = (id, body) => call(`/api/analytics/followups/${id}`, { method: 'POST', body });
export const getConsent = (studentId) => call(`/api/consent/${studentId}`);
