import { apiCall } from './client';

export const getTrackerDay = ({ dayIndex, batch }) =>
  apiCall('tracker.day', { dayIndex, batch });
