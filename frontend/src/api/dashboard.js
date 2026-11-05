import { apiCall } from "./client";
import { apiCall as backendApiCall } from "./backendClient";

export const getKpis = () =>
  backendApiCall("/api/student-dashboard/dashboard/kpis", { method: "GET" });
export const getRecentActivity = () => apiCall("dashboard.recentActivity");
export const getWeeklyStudy = () => apiCall("dashboard.weeklyStudy");
export const getAttendanceTrend = () => apiCall("dashboard.attendanceTrend");
export const getPerformanceMix = () =>
  backendApiCall("/api/student-dashboard/dashboard/performance-mix", {
    method: "GET",
  });
export const getBatchOverview = () => apiCall("dashboard.batchOverview");
export const getUpcomingTasks = () => apiCall("dashboard.upcomingTasks");
export const getMentorNotifications = () => apiCall("dashboard.notifications");
