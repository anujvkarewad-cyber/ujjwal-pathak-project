import { normalizeStudentGroup } from './studentGroup';

// Same five-day window as the original student list, but only completed IST
// days: an unfinished today must not become a false absence.
export function workspaceMetricsWindow(now = new Date()) {
  const istDay = new Date(now.getTime() + 330 * 60000).toISOString().slice(0, 10);
  const end = new Date(`${istDay}T00:00:00Z`); end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(end); start.setUTCDate(start.getUTCDate() - 4);
  return { from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) };
}

// Identity/membership ALWAYS come from the current roster, never the report.
export function mergeWorkspaceStudentMetrics(roster = [], report) {
  const reliable = report?.rosterSource === 'Students Sheet';
  const byId = new Map();
  for (const row of report?.items || []) {
    const id = String(row.studentId || '').trim().toUpperCase();
    if (id) byId.set(id, byId.has(id) ? null : row);
  }
  return roster.map(student => {
    const clean = { ...student, attendance: null, status: null, risk: null, metricsReason: 'Current metrics unavailable' };
    if (student.mongoReady && student.accessEnabled === false) return { ...clean, status: 'Access off', metricsReason: 'Access is off; no absence/risk assessment' };
    if (!reliable) return clean;
    const row = byId.get(String(student.id || student.studentId || '').trim().toUpperCase());
    if (!row) return { ...clean, metricsReason: 'No unique record in the current tracker cohort' };
    // Exact cohort match: stale metrics cannot follow a moved student.
    if (row.batch !== student.batch || normalizeStudentGroup(row.group) !== normalizeStudentGroup(student.group)) return { ...clean, metricsReason: 'Metric membership changed; refresh before assessing' };
    if (!row.effectiveStart) return { ...clean, metricsReason: 'Tracker start date unknown; no absence assessment' };
    // The backend de-duplicates submissions and supplies only eligible dates,
    // respecting joining+1, batch/manual start, history floor and excuses.
    const submitted = row.submittedDates, missed = row.missedDates;
    if (!Array.isArray(submitted) || !Array.isArray(missed)) return clean;
    if (submitted.length !== row.submittedDays || missed.length !== row.missedDays) return clean;
    const eligible = [...submitted, ...missed];
    if (!eligible.length || new Set(eligible).size !== eligible.length || eligible.some(d => d < report.from || d > report.to)) return { ...clean, metricsReason: 'No assessable history in this period' };
    const attendance = Math.round(1000 * submitted.length / eligible.length) / 10;
    const risk = attendance < 70 ? 'At Risk' : attendance < 80 ? 'Watch' : 'Healthy';
    const recent = eligible.sort().slice(-3);
    const status = risk === 'At Risk' ? 'At Risk' : recent.some(d => submitted.includes(d)) ? 'Active' : 'Inactive';
    return { ...clean, attendance, risk, status, metricsReason: `${report.from} – ${report.to}; excused days excluded` };
  });
}
