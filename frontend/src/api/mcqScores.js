import { apiCall } from './backendClient';

/**
 * MCQ Scores aggregate for the dashboard (per-student attempts/marks/average/
 * best/lastAttempt + cohort stats). Backed by ``GET /api/mentor/mcq-scores``.
 *
 * @param {object} opts
 * @param {'7'|'30'|'90'|'all'} [opts.range] time window over completedAt
 * @param {string}  [opts.q]    search by student name / id / batch
 * @param {string}  [opts.kind] optional source filter (daily|practice|mentor-test)
 */
export const getMcqScores = ({ range = '30', q = '', kind = '' } = {}) =>
  apiCall('/api/mentor/mcq-scores', { params: { range, q, kind } });
