import { apiCall } from './client';

export const getLeaderboard = (mode = 'overall') =>
  apiCall('leaderboard.list', { mode });
