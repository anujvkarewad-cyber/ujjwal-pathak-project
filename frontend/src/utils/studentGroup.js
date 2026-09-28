export const TRACKER_GROUP_FILTERS = ['All Groups', 'Group 1', 'Group 2', 'Both Groups'];

export function normalizeStudentGroup(value) {
  const text = String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
  if (!text) return 'unknown';
  if (/\b(both|combined)\b/.test(text)) return 'both';
  if (/group\s*(?:1|i)\s*(?:&|and|\+|\/)\s*(?:group\s*)?(?:2|ii)\b/.test(text)) return 'both';
  const hasGroupTwo = /(?:group|g)\s*(?:2|ii)\b/.test(text);
  const hasGroupOne = /(?:group|g)\s*(?:1|i)\b/.test(text);
  if (hasGroupOne && hasGroupTwo) return 'both';
  if (hasGroupOne) return 'group1';
  if (hasGroupTwo) return 'group2';
  return 'unknown';
}

export function matchesStudentGroup(value, filter) {
  if (!filter || filter === 'All Groups') return true;
  const wanted = ({ 'Group 1': 'group1', 'Group 2': 'group2', 'Both Groups': 'both' })[filter];
  return Boolean(wanted && normalizeStudentGroup(value) === wanted);
}
