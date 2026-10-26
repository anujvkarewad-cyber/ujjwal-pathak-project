// Mentor password reset — the app account and the Students sheet cell, changed together.
// See backend routers/password_reset.py. Nothing here sends or schedules anything:
// the new value is returned once, to this screen, for the mentor to pass on.
import { apiCall } from './backendClient';

export const fetchPasswordQueue = (days = 7) =>
  apiCall('/api/password-reset/queue', { params: { days } });

export const searchPasswordStudents = (q) =>
  apiCall('/api/password-reset/students', { params: { q } });

export const setStudentPassword = (body) =>
  apiCall('/api/password-reset/set', { method: 'POST', body });

// Retry only the sheet write, after the app was already updated.
export const syncPasswordToSheet = (studentId, password) =>
  apiCall('/api/password-reset/sheet-sync', { method: 'POST', body: { studentId, password } });

export const fetchPasswordHistory = (limit = 40) =>
  apiCall('/api/password-reset/history', { params: { limit } });
