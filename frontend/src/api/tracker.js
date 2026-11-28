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

// ── Daily Subject-Wise Solved Questions & Practice Sheets ──────────────────
export const SOLVED_QUESTION_SUBJECTS = [
  'Accounts',
  'Law',
  'DT',
  'GST',
  'Costing',
  'Audit',
  'FM',
  'SM',
];

export const resolveMentorProofUrl = (proofUrl) => {
  const raw = String(proofUrl || '').trim();
  if (!raw) return '';
  if (raw.startsWith('https://') || raw.startsWith('http://')) return raw;
  if (raw.startsWith('/api/proof-file')) {
    const match = raw.match(/[?&]fileId=([A-Za-z0-9_-]{5,200})/);
    if (match) return `https://drive.google.com/file/d/${match[1]}/view`;
  }
  return raw;
};

export const getSolvedQuestionsReport = ({ from, to, batch, group, subject }) =>
  backendApiCall('/api/student-dashboard/solved-questions-report', {
    params: { from, to, batch, group, subject },
  });

export const remindSolvedQuestions = ({ studentIds, date, subject, message }) =>
  backendApiCall('/api/student-dashboard/solved-questions-remind', {
    method: 'POST',
    body: { studentIds, date, subject, message },
  });
