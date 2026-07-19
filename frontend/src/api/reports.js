import { apiCall } from './client';

export const getBatchReport = () => apiCall('reports.batch');
export const getStudentReport = () => apiCall('reports.students');
