// Mentor test authoring for the dashboard — create, edit, publish, delete,
// plus question-paper / answer-sheet uploads.
//
// Reads and writes go to the FastAPI backend (/api/mentor/tests*, mentor JWT).
// The FILE upload is the one exception: only the mentor's own Apps Script can
// create files in his Drive (a service account has zero storage quota), so the
// browser posts the base64 to our backend and the backend hands it to Apps
// Script. Students read the published test from the backend, so nothing here
// depends on the Sheet.
import { apiCall } from './backendClient';

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MB — same cap as the app

export const listMentorTests = () => apiCall('/api/mentor/tests');

export const createMentorTest = (payload) =>
  apiCall('/api/mentor/tests', { method: 'POST', body: payload });

export const updateMentorTest = (testId, patch) =>
  apiCall(`/api/mentor/tests/${encodeURIComponent(testId)}`, { method: 'PATCH', body: patch });

export const setMentorTestPublished = (testId, published) =>
  apiCall(`/api/mentor/tests/${encodeURIComponent(testId)}/publish`, {
    method: 'POST',
    body: { published: !!published },
  });

export const deleteMentorTest = (testId) =>
  apiCall(`/api/mentor/tests/${encodeURIComponent(testId)}`, { method: 'DELETE' });

/** File → base64 (no data: prefix) + the browser's idea of its MIME type. */
export function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read the file. Try again.'));
    reader.onload = () => {
      const text = String(reader.result || '');
      const comma = text.indexOf(',');
      resolve({
        base64: comma >= 0 ? text.slice(comma + 1) : text,
        mimeType: file.type || 'application/pdf',
      });
    };
    reader.readAsDataURL(file);
  });
}

export const formatBytes = (bytes) => {
  const n = Number(bytes || 0);
  if (!n) return '0 KB';
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1048576).toFixed(2)} MB`;
};

/**
 * Upload one file (question paper / answer sheet).
 * Returns { fileId, viewUrl, downloadUrl, fileName, bytes }.
 */
export async function uploadTestFile({ kind, file }) {
  if (!file) throw new Error('Choose a file first.');
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error('File is larger than 10 MB. Compress the PDF and try again.');
  }
  const { base64, mimeType } = await readFileAsBase64(file);
  return apiCall('/api/mentor/tests/upload', {
    method: 'POST',
    body: { kind, filename: file.name || `${kind}.pdf`, mimeType, base64 },
  });
}
