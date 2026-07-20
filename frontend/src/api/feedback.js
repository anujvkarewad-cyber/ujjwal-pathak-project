import { apiCall } from './client';

export const sendFeedback = (payload) =>
  apiCall('feedback.send', payload);

export const getFeedback = (studentId) =>
  apiCall('feedback.get', { studentId });

export const markFeedbackRead = (id) =>
  apiCall('feedback.read', { id });
