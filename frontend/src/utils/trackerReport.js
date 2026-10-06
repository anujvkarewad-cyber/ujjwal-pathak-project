export const ALL_TRACKER_BATCHES = 'all';
export const ALL_TRACKER_GROUPS = 'all';

export const TRACKER_GROUP_OPTIONS = [
  { value: ALL_TRACKER_GROUPS, label: 'All Groups' },
  { value: 'group1', label: 'Group 1' },
  { value: 'group2', label: 'Group 2' },
  { value: 'both', label: 'Both Groups' },
];

function normalizedText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

export function trackerGroupKey(value) {
  const group = normalizedText(value);
  if (group.includes('both')) return 'both';
  if (/group\s*(2|ii)\b|^2$|^ii$/.test(group)) return 'group2';
  if (/group\s*(1|i)\b|^1$|^i$/.test(group)) return 'group1';
  return 'unassigned';
}

export function trackerBatchOptions(items = []) {
  const byKey = new Map();
  items.forEach((item) => {
    const label = String(item?.batch || '').trim();
    const key = normalizedText(label);
    if (key && !byKey.has(key)) byKey.set(key, label);
  });
  return [...byKey.entries()]
    .sort((left, right) => left[1].localeCompare(right[1], 'en', { sensitivity: 'base' }))
    .map(([value, label]) => ({ value, label }));
}

export function filterTrackerItems(items = [], batch = ALL_TRACKER_BATCHES, group = ALL_TRACKER_GROUPS) {
  return items.filter((item) => {
    const batchMatches = batch === ALL_TRACKER_BATCHES || normalizedText(item?.batch) === batch;
    const groupMatches = group === ALL_TRACKER_GROUPS || trackerGroupKey(item?.group) === group;
    return batchMatches && groupMatches;
  });
}

function isoDatesBetween(from, to) {
  if (!from || !to || from > to) return [];
  const dates = [];
  const cursor = new Date(`${from}T00:00:00Z`);
  const end = new Date(`${to}T00:00:00Z`);
  while (cursor <= end) {
    dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}

function trimFullHistoryToSelectedCohort(data, items) {
  if (data?.scope !== 'joined-to-date' || !items.length) return { from: data?.from, items };
  const cohortStart = items
    .map((row) => String(row.expectedFrom || row.joinedOn || data.from || ''))
    .filter(Boolean)
    .sort()[0] || data.from;
  const allDates = isoDatesBetween(cohortStart, data.to);
  const trimmed = items.map((row) => {
    const expectedFrom = String(row.expectedFrom || cohortStart) > cohortStart
      ? String(row.expectedFrom)
      : cohortStart;
    const expectedDates = allDates.filter((day) => day >= expectedFrom);
    const submittedSet = new Set((row.submittedDates || []).filter((day) => day >= expectedFrom && day <= data.to));
    const submittedDates = expectedDates.filter((day) => submittedSet.has(day));
    const missedDates = expectedDates.filter((day) => !submittedSet.has(day));
    return {
      ...row,
      expectedFrom,
      expectedDays: expectedDates.length,
      submittedDays: submittedDates.length,
      missedDays: missedDates.length,
      submittedDates,
      missedDates,
    };
  });
  return { from: cohortStart, items: trimmed };
}

export function reportWithTrackerItems(data, items) {
  if (!data) return null;
  const selected = [...(items || [])];
  const scoped = trimFullHistoryToSelectedCohort(data, selected);
  const filtered = scoped.items;
  const studentsWithMissedDays = filtered.filter((row) => Number(row.missedDays || 0) > 0).length;
  return {
    ...data,
    from: scoped.from,
    items: filtered,
    rosterCount: filtered.length,
    studentsWithMissedDays,
    studentsWithNoMissedDays: Math.max(0, filtered.length - studentsWithMissedDays),
  };
}

export function trackerScopeSlug(batchLabel, groupLabel) {
  const text = `${batchLabel || 'all-batches'}-${groupLabel || 'all-groups'}`
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return text || 'all-students';
}
