// React Query hooks for the NEW AI Content + Analytics APIs.
// Separate from hooks.js — existing pages/hooks are untouched.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as contentApi from './content';
import * as analyticsApi from './analytics';

// ── AI Content ────────────────────────────────────────────────────────────
export const useReviewQueue = (params) =>
  useQuery({ queryKey: ['content.queue', params], queryFn: () => contentApi.listQueue(params), enabled: params !== null });
export const useQuestion = (id) =>
  useQuery({ queryKey: ['content.question', id], queryFn: () => contentApi.getQuestion(id), enabled: !!id });
export const useScenario = (id) =>
  useQuery({ queryKey: ['content.scenario', id], queryFn: () => contentApi.getScenario(id), enabled: !!id });
export const useChapters = (params = {}) =>
  useQuery({ queryKey: ['content.chapters', params], queryFn: () => contentApi.listChapters(params) });
export const useChapterGate = (id) =>
  useQuery({ queryKey: ['content.gate', id], queryFn: () => contentApi.getChapterGate(id), enabled: !!id });
export const useReleases = () => useQuery({ queryKey: ['content.releases'], queryFn: () => contentApi.listReleases() });
export const useAudit = (params = {}) =>
  useQuery({ queryKey: ['content.audit', params], queryFn: () => contentApi.listAudit(params) });
export const useValidationDetail = (id) =>
  useQuery({ queryKey: ['content.validation', id], queryFn: () => contentApi.validationDetail(id), enabled: !!id });

export const useUpdateQuestion = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }) => contentApi.updateQuestion(id, patch),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['content.question', vars.id] });
      qc.invalidateQueries({ queryKey: ['content.queue'] });
      qc.invalidateQueries({ queryKey: ['content.validation', vars.id] });
    },
  });
};

export const useDecideQuestion = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision, comment, warningsAcknowledged, attemptSpecificRiskConfirmed }) =>
      contentApi.decideQuestion(id, { decision, comment, warningsAcknowledged, attemptSpecificRiskConfirmed }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['content.question'] });
      qc.invalidateQueries({ queryKey: ['content.queue'] });
      qc.invalidateQueries({ queryKey: ['content.chapters'] });
      qc.invalidateQueries({ queryKey: ['content.audit'] });
    },
  });
};

export const useDecideScenario = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision, comment, warningsAcknowledged, attemptSpecificRiskConfirmed }) =>
      contentApi.decideScenario(id, { decision, comment, warningsAcknowledged, attemptSpecificRiskConfirmed }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['content.scenario'] });
      qc.invalidateQueries({ queryKey: ['content.queue'] });
      qc.invalidateQueries({ queryKey: ['content.chapters'] });
      qc.invalidateQueries({ queryKey: ['content.audit'] });
    },
  });
};

export const useApproveChapter = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id) => contentApi.approveChapter(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['content.chapters'] });
      qc.invalidateQueries({ queryKey: ['content.gate'] });
      qc.invalidateQueries({ queryKey: ['content.audit'] });
    },
  });
};

// ── Analytics ─────────────────────────────────────────────────────────────
export const useAnalyticsOverview = () => useQuery({ queryKey: ['analytics.overview'], queryFn: analyticsApi.analyticsOverview });
export const useStudentsList = () => useQuery({ queryKey: ['analytics.students'], queryFn: analyticsApi.studentsList });
export const useStudentAnalysis = (id) =>
  useQuery({ queryKey: ['analytics.student', id], queryFn: () => analyticsApi.studentAnalysis(id), enabled: !!id });
export const useHeatmap = (params = {}) =>
  useQuery({ queryKey: ['analytics.heatmap', params], queryFn: () => analyticsApi.heatmap(params) });
export const useWeakChapters = (params = {}) =>
  useQuery({ queryKey: ['analytics.weakChapters', params], queryFn: () => analyticsApi.weakChapters(params) });
export const useGroupAnalysis = () => useQuery({ queryKey: ['analytics.groups'], queryFn: analyticsApi.groupAnalysis });
export const useAtRisk = () => useQuery({ queryKey: ['analytics.atRisk'], queryFn: analyticsApi.atRisk });
export const useImprovement = () => useQuery({ queryKey: ['analytics.improvement'], queryFn: analyticsApi.improvement });
export const useInactive = (params = {}) =>
  useQuery({ queryKey: ['analytics.inactive', params], queryFn: () => analyticsApi.inactiveStudents(params) });
export const useFollowups = (params = {}) =>
  useQuery({ queryKey: ['analytics.followups', params], queryFn: () => analyticsApi.listFollowups(params) });
export const useCreateFollowup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => analyticsApi.createFollowup(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['analytics.followups'] }),
  });
};
export const useUpdateFollowup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }) => analyticsApi.updateFollowup(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analytics.followups'] });
      qc.invalidateQueries({ queryKey: ['analytics.overview'] });
    },
  });
};
