import { apiCall, apiCallLarge } from './client';

export const getNotes = () => apiCall('notes.list');

// payload: { title, description, subject, audience, fileName, mimeType, fileData }
// fileData must be base64 (no "data:application/pdf;base64," prefix).
export const createNote = (payload) => apiCallLarge('notes.create', payload);

export const deleteNote = (id) => apiCall('notes.delete', { id });
