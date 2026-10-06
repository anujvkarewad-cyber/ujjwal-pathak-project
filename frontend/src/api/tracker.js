import { apiCall } from './client';
import { apiCall as backendApiCall } from './backendClient';

export const getTrackerDay = ({ dayIndex, batch }) =>
  apiCall('tracker.day', { dayIndex, batch });

export const getMissedTrackerReport = ({ from, to, scope }) =>
  backendApiCall('/api/student-dashboard/tracker-missed-report', {
    params: { from, to, scope },
  });
