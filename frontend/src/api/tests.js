// Mentor test records — student test attempts synced from the UMP student app
// (MCQ tests auto-graded; paper tests with student self-evaluation marks).
import { apiCall } from './backendClient';

export const fetchTestHistory = (studentId) =>
  apiCall('/api/test-history', { params: studentId ? { student_id: studentId } : null });

export const fetchStudentTestHistory = (studentId) =>
  apiCall(`/api/test-history/${encodeURIComponent(studentId)}`);

// Attempts folded per test, plus each test's audience split into
// submitted / still missing. See backend routers/test_history.py.
export const fetchTestHistoryGroups = () => apiCall('/api/test-history/groups');

// Manual-only: ping exactly the students listed as "still missing" for one test.
// There is no scheduled/auto variant anywhere in the app - by owner decision 16-Oct-2026.
export const notifyMissingSubmissions = (testKey, message) =>
  apiCall(`/api/test-history/groups/${encodeURIComponent(testKey)}/notify`, {
    method: 'POST',
    body: message ? { message } : {},
  });
