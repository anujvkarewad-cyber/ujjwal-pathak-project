import { apiCall } from './backendClient';

/** Mentor Notes Inbox (server-side, replaces the Apps Script inbox). */
export const getInbox = () => apiCall('/api/notes-inbox');

export const publishInboxFile = ({ fileId, batches, group, subject, title, series, chapter, category }) =>
  apiCall('/api/notes-inbox/publish', {
    method: 'POST',
    body: { fileId, batches, group, subject, title, series, chapter, category },
  });

export const skipInboxFile = (fileId) =>
  apiCall('/api/notes-inbox/skip', { method: 'POST', body: { fileId } });
