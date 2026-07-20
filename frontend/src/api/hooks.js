// React Query hooks. All pages/components consume data via these hooks.
// Swapping to Google Apps Script requires zero changes here — only api/config.js.

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import * as studentsApi from './students';
import * as dashboardApi from './dashboard';
import * as trackerApi from './tracker';
import * as leaderboardApi from './leaderboard';
import * as announcementsApi from './announcements';
import * as reportsApi from './reports';
import * as mentorApi from './mentor';
import * as feedbackApi from './feedback';

// ── Students ────────────────────────────────────────────────────────────
export const useStudents = () =>
  useQuery({ queryKey: ['students'], queryFn: studentsApi.getStudents });

export const useStudent = (id) =>
  useQuery({ queryKey: ['student', id], queryFn: () => studentsApi.getStudentById(id), enabled: !!id });

export const useAddMentorNote = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }) => studentsApi.addMentorNote(id, note),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['student', vars.id] });
    },
  });
};

// ── Dashboard ───────────────────────────────────────────────────────────
export const useDashboardKpis = () =>
  useQuery({ queryKey: ['dashboard', 'kpis'], queryFn: dashboardApi.getKpis });
export const useRecentActivity = () =>
  useQuery({ queryKey: ['dashboard', 'recentActivity'], queryFn: dashboardApi.getRecentActivity });
export const useWeeklyStudy = () =>
  useQuery({ queryKey: ['dashboard', 'weeklyStudy'], queryFn: dashboardApi.getWeeklyStudy });
export const useAttendanceTrend = () =>
  useQuery({ queryKey: ['dashboard', 'attendanceTrend'], queryFn: dashboardApi.getAttendanceTrend });
export const usePerformanceMix = () =>
  useQuery({ queryKey: ['dashboard', 'performanceMix'], queryFn: dashboardApi.getPerformanceMix });
export const useBatchOverview = () =>
  useQuery({ queryKey: ['dashboard', 'batchOverview'], queryFn: dashboardApi.getBatchOverview });
export const useUpcomingTasks = () =>
  useQuery({ queryKey: ['dashboard', 'upcomingTasks'], queryFn: dashboardApi.getUpcomingTasks });

// ── Daily Tracker ───────────────────────────────────────────────────────
export const useTrackerDay = ({ dayIndex, batch }) =>
  useQuery({
    queryKey: ['tracker', dayIndex, batch],
    queryFn: () => trackerApi.getTrackerDay({ dayIndex, batch }),
    enabled: dayIndex != null,
  });

// ── Leaderboard ─────────────────────────────────────────────────────────
export const useLeaderboard = (mode = 'overall') =>
  useQuery({ queryKey: ['leaderboard', mode], queryFn: () => leaderboardApi.getLeaderboard(mode) });

// ── Announcements ───────────────────────────────────────────────────────
export const useAnnouncements = () =>
  useQuery({ queryKey: ['announcements'], queryFn: announcementsApi.getAnnouncements });

export const useCreateAnnouncement = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: announcementsApi.createAnnouncement,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['announcements'] }),
  });
};

export const useTogglePinAnnouncement = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => announcementsApi.togglePinAnnouncement(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['announcements'] }),
  });
};

// ── Reports ─────────────────────────────────────────────────────────────
export const useBatchReport = () =>
  useQuery({ queryKey: ['reports', 'batch'], queryFn: reportsApi.getBatchReport });
export const useStudentReport = () =>
  useQuery({ queryKey: ['reports', 'students'], queryFn: reportsApi.getStudentReport });

// ── Mentor / Settings ───────────────────────────────────────────────────
export const useMentorProfile = () =>
  useQuery({ queryKey: ['mentor'], queryFn: mentorApi.getMentorProfile });

export const useUpdateMentorProfile = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: mentorApi.updateMentorProfile,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mentor'] }),
  });
};

export const useNotificationSettings = () =>
  useQuery({ queryKey: ['notifications'], queryFn: mentorApi.getNotificationSettings });

export const useUpdateNotificationSettings = () => {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: mentorApi.updateNotificationSettings,
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
};

// ── Feedback ─────────────────────────────────────────────

export const useSendFeedback = () => {
  return useMutation({
    mutationFn: feedbackApi.sendFeedback,
  });
};

export const useStudentFeedback = (studentId) =>
  useQuery({
    queryKey: ['feedback', studentId],
    queryFn: () => feedbackApi.getFeedback(studentId),
    enabled: !!studentId,
  });

export const useMarkFeedbackRead = () => {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: feedbackApi.markFeedbackRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback'] });
    },
  });
};
  return useMutation({
    mutationFn: mentorApi.updateNotificationSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
};
