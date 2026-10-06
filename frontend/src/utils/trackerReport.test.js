import {
  ALL_TRACKER_BATCHES,
  ALL_TRACKER_GROUPS,
  filterTrackerItems,
  reportWithTrackerItems,
  trackerBatchOptions,
  trackerGroupKey,
  trackerScopeSlug,
} from './trackerReport';

const items = [
  { studentId: 'UMP0001', batch: 'Before Result Batch 1', group: 'Group 1', missedDays: 2 },
  { studentId: 'UMP0002', batch: 'Before Result Batch 1', group: 'Group 2', missedDays: 0 },
  { studentId: 'UMP0003', batch: 'Before Result Batch 2', group: 'Group 1', missedDays: 1 },
  { studentId: 'UMP0004', batch: 'Before Result Batch 1', group: 'Both', missedDays: 0 },
];

test('normalizes tracker group labels', () => {
  expect(trackerGroupKey('Group 1')).toBe('group1');
  expect(trackerGroupKey('Group I')).toBe('group1');
  expect(trackerGroupKey('group2')).toBe('group2');
  expect(trackerGroupKey('Group II')).toBe('group2');
  expect(trackerGroupKey('Both Groups')).toBe('both');
});

test('filters a tracker report by both batch and group', () => {
  expect(filterTrackerItems(items, 'before result batch 1', 'group1').map((row) => row.studentId))
    .toEqual(['UMP0001']);
  expect(filterTrackerItems(items, 'before result batch 1', ALL_TRACKER_GROUPS).map((row) => row.studentId))
    .toEqual(['UMP0001', 'UMP0002', 'UMP0004']);
  expect(filterTrackerItems(items, ALL_TRACKER_BATCHES, 'group1').map((row) => row.studentId))
    .toEqual(['UMP0001', 'UMP0003']);
});

test('creates sorted unique batch options', () => {
  expect(trackerBatchOptions(items)).toEqual([
    { value: 'before result batch 1', label: 'Before Result Batch 1' },
    { value: 'before result batch 2', label: 'Before Result Batch 2' },
  ]);
});

test('recalculates report totals for the selected cohort only', () => {
  const selected = filterTrackerItems(items, 'before result batch 1', ALL_TRACKER_GROUPS);
  const report = reportWithTrackerItems({ items, rosterCount: 4 }, selected);
  expect(report.rosterCount).toBe(3);
  expect(report.studentsWithMissedDays).toBe(1);
  expect(report.studentsWithNoMissedDays).toBe(2);
});

test('uses batch and group in safe download filenames', () => {
  expect(trackerScopeSlug('Before Result Batch 1', 'Group 1'))
    .toBe('before-result-batch-1-group-1');
});
