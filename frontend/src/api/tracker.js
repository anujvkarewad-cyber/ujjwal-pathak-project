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

// Batch start dates + per-student tracker start overrides (mentor-editable).
export const getTrackerStartConfig = () =>
  backendApiCall('/api/student-dashboard/tracker-start-config');

export const saveTrackerStartConfig = (body) =>
  backendApiCall('/api/student-dashboard/tracker-start-config', {
    method: 'POST',
    body,
  });

// ── Leave / absent (owner spec 14-Oct-2026) ────────────────────────────────
// Students declare leave/absent from the app; the mentor sees it in the day
// view and can change or cancel it (mentor override always wins).
export const getAttendanceDay = ({ date }) =>
  backendApiCall('/api/attendance/mentor/day', { params: { date } });

export const getStudentAttendance = (studentId) =>
  backendApiCall(`/api/attendance/mentor/student/${studentId}`);

export const markMentorLeave = ({ studentId, from, to, reason }) =>
  backendApiCall('/api/attendance/mentor/leave', {
    method: 'POST',
    body: { studentId, from, to, reason },
  });

export const markMentorAbsent = ({ studentId, date, reason }) =>
  backendApiCall('/api/attendance/mentor/absent', {
    method: 'POST',
    body: { studentId, date, reason },
  });

export const cancelAttendance = ({ leaveId, studentId, date }) =>
  backendApiCall('/api/attendance/mentor/cancel', {
    method: 'POST',
    body: { leaveId, studentId, date },
  });
