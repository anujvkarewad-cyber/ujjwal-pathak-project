import { apiCall } from './backendClient';
export const getWorkspaceRoster = () => apiCall('/api/mentor-workspace/roster');
export const reviewWorkspaceOperation = body => apiCall('/api/mentor-workspace/review', { method: 'POST', body });
// One-shot send: the server runs the same recipient guards as a review and then
// commits in the same request. Used for plain messages/announcements so a mentor
// does not have to confirm twice. Transfers still use review + confirm.
export const sendWorkspaceNow = body => apiCall('/api/mentor-workspace/send', { method: 'POST', body });
export const commitWorkspaceOperation = id => apiCall(`/api/mentor-workspace/plans/${encodeURIComponent(id)}/commit`, { method: 'POST', body: { confirm: 'CONFIRM' } });
export const getWorkspacePlan = id => apiCall(`/api/mentor-workspace/plans/${encodeURIComponent(id)}`);
export const getWorkspaceAnnouncements = () => apiCall('/api/mentor-workspace/announcements');

export const reconcileWorkspacePlan = id => apiCall(`/api/mentor-workspace/plans/${encodeURIComponent(id)}/reconcile`, { method: 'POST', body: { confirm: 'RECONCILE' } });
