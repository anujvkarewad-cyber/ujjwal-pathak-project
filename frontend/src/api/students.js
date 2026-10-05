import { apiCall } from './client';
import { apiCall as backendApiCall } from './backendClient';

export const getStudents = () => apiCall('students.list');
export const getStudentById = (id) => apiCall('students.get', { id });
export const addMentorNote = (id, note) => apiCall('students.addNote', { id, note });

// Batch corrections are privileged writes. They go through the authenticated
// FastAPI backend, never directly from the browser to the public Apps Script.
export const changeStudentBatch = ({ id, batch, expectedBatch }) =>
  backendApiCall(`/api/student-auth/students/${encodeURIComponent(id)}/batch`, {
    method: 'PATCH',
    body: { batch, expectedBatch },
  });
