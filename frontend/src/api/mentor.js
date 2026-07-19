import { apiCall } from './client';

export const getMentorProfile = () => apiCall('mentor.get');
export const updateMentorProfile = (payload) => apiCall('mentor.update', payload);
export const getNotificationSettings = () => apiCall('notifications.get');
export const updateNotificationSettings = (payload) => apiCall('notifications.update', payload);
