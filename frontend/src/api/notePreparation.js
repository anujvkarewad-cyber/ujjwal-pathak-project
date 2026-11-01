import { apiUrl, getToken, AUTH_EVENT } from './backendClient';

export const preparationMessage = (reason) => ({
  optimized: 'Optimized; review small text and diagrams before upload.',
  original_selected: 'Original quality selected; bytes unchanged.',
  encrypted_pdf: 'Encrypted PDF retained unchanged.',
  forms_or_signatures: 'Form or signed PDF retained unchanged.',
  no_meaningful_saving: 'Already efficient; original retained.',
  page_limit: 'Document exceeds preparation page limit; original retained.',
  processing_timeout: 'Preparation timed out; original retained.',
  processing_failed: 'Could not safely optimize this PDF; original retained.',
  optimizer_unavailable: 'Optimizer unavailable; original retained.',
  verification_failed: 'Safety verification failed; original retained.',
  preparation_unavailable: 'Preparation service unavailable; original will be uploaded.',
}[reason] || 'Original retained; optimization was not completed.');

export function preparationWithinBudget(files) {
  return files.length <= 25 && files.reduce((sum, file) => sum + file.size, 0) <= 100 * 1024 * 1024;
}

export function originalEntry(file, reason = 'original_selected') {
  return { original: file, file, status: 'original', reason, useOriginal: true };
}

export function selectedNoteFile(entry) {
  return entry.useOriginal ? entry.original : entry.file;
}

export function preparedMatches(files, prepared) {
  return files.length > 0 && files.length === prepared.length &&
    files.every((file, index) => prepared[index]?.original === file);
}

export async function prepareNote(file, { signal, fetchImpl = fetch } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, 90000);
  try {
    const token = getToken();
    const response = await fetchImpl(apiUrl('/api/mentor/notes/prepare?quality=balanced'), {
      method: 'POST', body: file, signal: controller.signal,
      headers: { 'Content-Type': 'application/pdf', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (response.status === 401 || response.status === 403) {
      if (response.status === 401) window.dispatchEvent(new CustomEvent(AUTH_EVENT));
      const error = new Error('Mentor authentication required. Preparation stopped; nothing was published.');
      error.authRequired = true;
      throw error;
    }
    if (!response.ok || !(response.headers.get('content-type') || '').includes('application/pdf')) {
      return originalEntry(file, 'preparation_unavailable');
    }
    const bytes = await response.arrayBuffer();
    const status = response.headers.get('x-notes-status');
    const reason = response.headers.get('x-notes-reason');
    if (Number(response.headers.get('x-notes-original-bytes')) !== file.size ||
        Number(response.headers.get('x-notes-output-bytes')) !== bytes.byteLength ||
        !new TextDecoder().decode(bytes.slice(0, 64)).trimStart().startsWith('%PDF-')) {
      return originalEntry(file, 'verification_failed');
    }
    if (status !== 'compressed' || bytes.byteLength >= file.size) return originalEntry(file, reason);
    return { original: file, file: new File([bytes], file.name, { type: 'application/pdf', lastModified: file.lastModified }),
      status, reason: 'optimized', useOriginal: false };
  } catch (error) {
    if (error.authRequired || signal?.aborted) throw error;
    return originalEntry(file, error.name === 'AbortError' ? 'processing_timeout' : 'preparation_unavailable');
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
}
