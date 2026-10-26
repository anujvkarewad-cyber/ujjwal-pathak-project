import { normalizeStudentGroup } from './studentGroup';

export const WORKSPACE_GROUPS = [
  { key: 'group1', label: 'Group 1', trackerLabel: 'Group 1' },
  { key: 'group2', label: 'Group 2', trackerLabel: 'Group 2' },
  { key: 'both', label: 'Both', trackerLabel: 'Both Groups' },
];

// Only populated, current-roster batches. Never seed planned/demo batches.
export function currentBatchNames(students = []) {
  return [...new Set(students.map(s => String(s.batch || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'en', { sensitivity: 'base' }));
}
export function workspaceStudents(students = [], batch, groupKey) {
  if (!batch || !WORKSPACE_GROUPS.some(g => g.key === groupKey)) return [];
  return students.filter(s => String(s.batch || '').trim() === batch && normalizeStudentGroup(s.group) === groupKey);
}
