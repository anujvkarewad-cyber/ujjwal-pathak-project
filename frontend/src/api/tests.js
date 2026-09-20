// Mentor test records — student test attempts synced from the UMP student app
// (MCQ tests auto-graded; paper tests with student self-evaluation marks).
import { apiCall } from './backendClient';

export const fetchTestHistory = (studentId) =>
  apiCall('/api/test-history', { params: studentId ? { student_id: studentId } : null });

export const fetchStudentTestHistory = (studentId) =>
  apiCall(`/api/test-history/${encodeURIComponent(studentId)}`);
