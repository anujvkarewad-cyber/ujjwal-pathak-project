import { apiCall } from './client';
import { apiCall as backendCall } from './backendClient';

export const getAnnouncements = async () => {
  const [rows, deletionState, workspace] = await Promise.all([
    apiCall('announcements.list'),
    backendCall('/api/student-dashboard/announcements/deleted'),
    backendCall('/api/mentor-workspace/announcements'),
  ]);
  const deleted = new Set(deletionState.deletedIds || []);
  return [...(workspace.announcements || []), ...(Array.isArray(rows) ? rows : [])].filter((row) => !deleted.has(String(row.id || '').trim()));
};
export const createAnnouncement = async (payload) => {
  const created = await apiCall('announcements.create', payload);
  // Push the published announcement to targeted students' devices. Best-effort:
  // the in-app announcement already exists, so a push failure never breaks create.
  try {
    await backendCall('/api/student-dashboard/announcements/notify', {
      method: 'POST',
      body: {
        title: String(payload?.title || created?.title || '').trim(),
        body: String(payload?.body || created?.body || '').trim(),
        audience: String(payload?.audience || created?.audience || 'All Batches').trim(),
      },
    });
  } catch (_) {
    /* push is best-effort */
  }
  return created;
};
export const togglePinAnnouncement = (id) => String(id).startsWith('WS-') ? backendCall(`/api/mentor-workspace/announcements/${encodeURIComponent(id)}/pin`, { method: 'POST' }) : apiCall('announcements.togglePin', { id });
export const deleteAnnouncement = (id) => backendCall(`/api/student-dashboard/announcements/${encodeURIComponent(id)}`, { method: 'DELETE' });
