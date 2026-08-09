import { apiCall, apiCallLarge, apiCallLargeWithProgress, apiCallWithRetry } from './client';

export const getNotes = () => apiCall('notes.list');

// payload: { title, description, subject, audience, fileName, mimeType, fileData }
// fileData must be base64 (no "data:application/pdf;base64," prefix).
export const createNote = (payload) => apiCallLarge('notes.create', payload);

export const deleteNote = (id) => apiCall('notes.delete', { id });

// Single-shot upload with native XHR progress. Kept for reference / small
// payloads, but for PDF notes prefer createNoteChunked below — a single
// large POST to Apps Script gets less reliable as the body grows (see the
// transport note in client.js), which is what "Network error during
// upload" on bigger files usually means.
export const createNoteWithProgress = (payload, onProgress) =>
  apiCallLargeWithProgress('notes.create', payload, onProgress);

// Chunk size in base64 CHARACTERS (== bytes, since base64 is ASCII).
// Google Apps Script's CacheService caps each stored value at 100KB
// (102,400 bytes) — this stays comfortably under that with margin for the
// surrounding JSON payload.
const CHUNK_SIZE = 90000;

function makeUploadId() {
  return 'up_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}

// Uploads a large base64 PDF in small chunks instead of one big POST.
// Google Apps Script Web Apps become progressively less reliable at
// handling large POST bodies (there's no single hard limit — it's a
// reliability curve, see client.js) — chunking keeps every individual
// request small and gives each one a couple of automatic retries, so one
// flaky request doesn't fail the whole upload.
//
// payload: { title, description, subject, audience, group, fileName,
//            mimeType, fileData (base64, no data: prefix) }
// onProgress({ loaded, total, percent }) — loaded/total are RAW file bytes,
// not base64 length, so the caller's progress bar matches the file size
// shown in the UI.
export async function createNoteChunked(payload, onProgress) {
  const { fileData, ...metadata } = payload;
  if (!fileData) throw new Error('File data is required');

  const uploadId = makeUploadId();
  const totalChunks = Math.max(1, Math.ceil(fileData.length / CHUNK_SIZE));
  // base64 is ~4/3 the size of the original bytes — scale back down so the
  // progress bar reflects the real file size, not the inflated encoding.
  const rawTotalBytes = Math.floor((fileData.length * 3) / 4);

  for (let i = 0; i < totalChunks; i++) {
    const chunk = fileData.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);

    await apiCallWithRetry(
      () => apiCallLarge('notes.uploadChunk', {
        uploadId,
        chunkIndex: i,
        totalChunks,
        data: chunk,
      }),
      3,   // attempts per chunk
      600  // 600ms, 1200ms retry backoff
    );

    if (onProgress) {
      const loaded = Math.min(rawTotalBytes, Math.round(((i + 1) / totalChunks) * rawTotalBytes));
      onProgress({
        loaded,
        total: rawTotalBytes,
        percent: Math.round(((i + 1) / totalChunks) * 100),
      });
    }
  }

  // All chunks are stored server-side — ask Apps Script to reassemble them,
  // decode the PDF, save it to Drive, and write the Notes row.
  return apiCallWithRetry(
    () => apiCallLarge('notes.finalizeUpload', { uploadId, totalChunks, ...metadata }),
    3,
    800
  );
}
