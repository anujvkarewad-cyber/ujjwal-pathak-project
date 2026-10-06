import { apiCall as backendApiCall } from './backendClient';

// The live day view merges current app/Mongo study logs with legacy Google
// Form responses. Reading Apps Script alone misses submissions made in the APK.
export const getTrackerDay = ({ dayIndex, batch }) =>
  backendApiCall('/api/student-dashboard/tracker-day', {
    params: { dayIndex, batch },
  });

export const getMissedTrackerReport = ({ from, to, scope }) =>
  backendApiCall('/api/student-dashboard/tracker-missed-report', {
    params: { from, to, scope },
  });
