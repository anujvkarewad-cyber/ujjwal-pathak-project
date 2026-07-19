import { apiCall } from './client';

export const getStudents = () => apiCall('students.list');
export const getStudentById = (id) => apiCall('students.get', { id });
export const addMentorNote = (id, note) => apiCall('students.addNote', { id, note });
