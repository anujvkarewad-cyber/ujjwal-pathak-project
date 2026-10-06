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

export function reportWithTrackerItems(data, items) {
  if (!data) return null;
  const filtered = [...(items || [])];
  const studentsWithMissedDays = filtered.filter((row) => Number(row.missedDays || 0) > 0).length;
  return {
    ...data,
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
