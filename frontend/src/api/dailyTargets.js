import { apiCall } from './backendClient';

export const fetchTargetOptions = () => apiCall('/api/targets/options');
export const previewTargetAudience = (params) => apiCall('/api/targets/preview', { params });
export const fetchTargets = () => apiCall('/api/targets');
export const publishTarget = (body) => apiCall('/api/targets', { method: 'POST', body });
export const removeTarget = (id) => apiCall(`/api/targets/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const regenerateTargetReminder = (id) => apiCall(`/api/targets/${encodeURIComponent(id)}/reminder`, { method: 'POST' });
