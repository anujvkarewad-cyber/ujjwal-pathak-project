import { apiCall } from './client';
import { apiCall as backendCall } from './backendClient';

export const getAnnouncements = async () => {
  const [rows, deletionState] = await Promise.all([
    apiCall('announcements.list'),
    backendCall('/api/student-dashboard/announcements/deleted'),
  ]);
  const deleted = new Set(deletionState.deletedIds || []);
  return (Array.isArray(rows) ? rows : []).filter((row) => !deleted.has(String(row.id || '').trim()));
};
export const createAnnouncement = (payload) => apiCall('announcements.create', payload);
export const togglePinAnnouncement = (id) => apiCall('announcements.togglePin', { id });
export const deleteAnnouncement = (id) => backendCall(`/api/student-dashboard/announcements/${encodeURIComponent(id)}`, { method: 'DELETE' });
