import { apiCall } from "./client";
import { apiCall as backendApiCall } from "./backendClient";

export const getStudents = () =>
  backendApiCall("/api/student-dashboard/students/directory", {
    method: "GET",
  }).then((res) => ({
    students: res.students || [],
    options: res.options || {
      batchOptions: ["All Batches"],
      attemptOptions: ["All Attempts"],
      groupOptions: ["All Groups"],
      statusOptions: ["All Status", "Active", "Removed"],
    },
  }));
export const getStudentById = (id) =>
  backendApiCall(
    `/api/student-dashboard/students/${encodeURIComponent(id)}/profile`,
    {
      method: "GET",
    },
  ).then((res) => ({
    id: res.studentId || res.id,
    studentId: res.studentId || res.id,
    name: res.name,
    avatar: res.avatar,
    email: res.email,
    phone: res.phone,
    city: res.city,
    joinedOn: res.joinedOn,
    batch: res.batch,
    group: res.group,
    attempt: res.attempt,
    level: res.level,
    status: res.status,
    risk: res.risk,
    attendance: res.attendance,
    studyHours: res.studyHours,
    submissionRate: res.submissionRate,
    totalHours: res.totalHours,
    streak: res.streak,
    lastSubmission: res.lastSubmission,
    accessEnabled: res.accessEnabled,
    accessReason: res.accessReason,
    weekly: res.weekly || [],
    monthly: res.monthly || [],
    tracker: res.tracker || [],
    mentorNotes: res.mentorNotes || [],
    feedback: res.feedback || [],
  }));
export const addMentorNote = (id, note) =>
  apiCall("students.addNote", { id, note });

// Batch corrections are privileged writes. They go through the authenticated
// FastAPI backend, never directly from the browser to the public Apps Script.
export const changeStudentBatch = ({ id, batch, expectedBatch }) =>
  backendApiCall(`/api/student-auth/students/${encodeURIComponent(id)}/batch`, {
    method: "PATCH",
    body: { batch, expectedBatch },
  });
