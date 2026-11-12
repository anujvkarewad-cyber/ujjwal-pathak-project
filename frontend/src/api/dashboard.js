import { apiCall } from "./client";
import { apiCall as backendApiCall } from "./backendClient";

// The mentor dashboard uses one live backend snapshot for all cards and charts.
export const getKpis = () =>
  backendApiCall("/api/student-dashboard/dashboard/kpis", { method: "GET" });

// Retained for the legacy top-bar notification control; dashboard analytics do
// not use the local/demo adapter anymore.
export const getMentorNotifications = () => apiCall("dashboard.notifications");
