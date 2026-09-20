// Student ↔ Mentor messenger (mentor side). Backed by the FastAPI
// /api/messages/* router; the student app writes to the same threads.
import { apiCall } from './backendClient';

export const fetchInbox = () => apiCall('/api/messages/inbox');
export const fetchThread = (studentId) => apiCall(`/api/messages/inbox/${encodeURIComponent(studentId)}`);
export const replyToStudent = (studentId, text) =>
  apiCall('/api/messages/reply', { method: 'POST', body: { studentId, text } });
export const fetchWhatsAppStatus = () => apiCall('/api/whatsapp/status');
export const fetchWhatsAppLog = () => apiCall('/api/whatsapp/log', { params: { limit: 12 } });
