import { apiCall } from './client';

export const getAnnouncements = () => apiCall('announcements.list');
export const createAnnouncement = (payload) => apiCall('announcements.create', payload);
export const togglePinAnnouncement = (id) => apiCall('announcements.togglePin', { id });
