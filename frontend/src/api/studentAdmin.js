import { apiCall as backendApiCall } from "./backendClient";

// Soft-remove flow (mentor-only): removing a student blocks app login and drops
// them from tracker views, leaderboards and pushes. Data is kept so a restore
// brings the account back intact.
export const removeStudent = (studentId, confirm = "") =>
  backendApiCall(
    `/api/student-dashboard/students/${encodeURIComponent(studentId)}/remove`,
    {
      method: "POST",
      body: { confirm },
    },
  );

export const restoreStudent = (studentId) =>
  backendApiCall(
    `/api/student-dashboard/students/${encodeURIComponent(studentId)}/restore`,
    {
      method: "POST",
    },
  );

export const getRemovedStudents = () =>
  backendApiCall("/api/student-dashboard/students/removed");

// Mentor-controlled access ON/OFF: blocks the student's app access with a
// visible reason (the original owner workflow for non-studious students).
export const setStudentAccess = (studentId, enabled, reason = "") =>
  backendApiCall(
    `/api/student-dashboard/students/${encodeURIComponent(studentId)}/access`,
    {
      method: "POST",
      body: { enabled, reason },
    },
  );

// Admin card state for the student profile (access + removal).
export const getAdminState = (studentId) =>
  backendApiCall(
    `/api/student-dashboard/students/${encodeURIComponent(studentId)}/admin-state`,
  );

// Sheet ⇄ Mongo batch drift. A student's own Profile shows the Students sheet,
// while test/notes/target/push audience comes from the app account - so a batch
// typed by hand into the sheet must be copied over deliberately, not assumed.
export const getBatchDrift = (refresh = false) =>
  backendApiCall(
    `/api/student-auth/students/batch-drift${refresh ? "?refresh=1" : ""}`,
  );

// Students whose app access is OFF (mentor blocked them). Used by the
// "Access Off" tab in the sidebar so the mentor can review and re-enable them.
export const getAccessOffStudents = () =>
  backendApiCall("/api/student-dashboard/students/access-off", {
    method: "GET",
  }).then((res) => ({
    students: res.students || [],
    count: res.count || 0,
  }));

export const applyBatchDrift = (studentIds) =>
  backendApiCall("/api/student-auth/students/batch-drift/apply", {
    method: "POST",
    body: { studentIds },
  });

// Progress meter for the sheet password ledger: how many active students' sheet
// cells still authenticate. Fills itself as those students sign in.
export const getCoverage = (refresh = false) =>
  backendApiCall(
    `/api/student-auth/students/password-coverage${refresh ? "?refresh=1" : ""}`,
  );

