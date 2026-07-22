import { apiCall } from './client';

export const getKpis = () => apiCall('dashboard.kpis');
export const getRecentActivity = () => apiCall('dashboard.recentActivity');
export const getWeeklyStudy = () => apiCall('dashboard.weeklyStudy');
export const getAttendanceTrend = () => apiCall('dashboard.attendanceTrend');
export const getPerformanceMix = () => apiCall('dashboard.performanceMix');
export const getBatchOverview = () => apiCall('dashboard.batchOverview');
export const getUpcomingTasks = () => apiCall('dashboard.upcomingTasks');
export const getMentorNotifications = () => apiCall('dashboard.notifications');