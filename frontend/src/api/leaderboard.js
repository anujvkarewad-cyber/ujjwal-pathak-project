import { apiCall as backendApiCall } from './backendClient';

// Ranking is computed by the mentor backend from live Mongo data.
//
// This page used to call the legacy Apps Script action `leaderboard.list` over
// JSONP. That action returned every student with zero stats and no rank field at
// all, so the UI invented ranks from array position. The authenticated backend
// endpoint is now the single source of truth and both the mentor page and the
// student app read the same numbers.
export const getLeaderboard = ({
  period = 'overall',
  segment = 'batch',
  batch,
  group,
  attempt,
} = {}) =>
  backendApiCall('/api/student-dashboard/leaderboard', {
    params: { period, segment, batch, group, attempt },
  });

// Per-week Top 3 history ("kis week kaun top 3"): one podium per calendar week.
export const getWeeklyTops = ({ weeks = 6, segment = 'batch', batch, group } = {}) =>
  backendApiCall('/api/student-dashboard/leaderboard/weekly-tops', {
    params: { weeks, segment, batch, group },
  });
