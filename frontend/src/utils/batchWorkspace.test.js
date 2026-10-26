import { currentBatchNames, workspaceStudents } from './batchWorkspace';
const roster = [
  { id: 'a', batch: 'Existing A', group: 'Group 1' },
  { id: 'b', batch: 'Existing A', group: 'Group 2' },
  { id: 'c', batch: 'Existing A', group: 'Both' },
  { id: 'd', batch: 'Existing A', group: '' },
  { id: 'e', batch: 'Existing B', group: 'Group I' },
];
test('only populated current batches appear; planned or demo batches are not seeded', () => {
  expect(currentBatchNames(roster)).toEqual(['Existing A', 'Existing B']);
  expect(currentBatchNames([])).toEqual([]);
});
test('exclusive membership: Both is not included in either single group', () => {
  expect(workspaceStudents(roster, 'Existing A', 'group1').map(s => s.id)).toEqual(['a']);
  expect(workspaceStudents(roster, 'Existing A', 'group2').map(s => s.id)).toEqual(['b']);
  expect(workspaceStudents(roster, 'Existing A', 'both').map(s => s.id)).toEqual(['c']);
});
test('unknown group never gets assigned or shown in an arbitrary workspace', () => {
  expect(workspaceStudents(roster, 'Existing A', 'unknown')).toEqual([]);
  expect(workspaceStudents(roster, '', 'group1')).toEqual([]);
});
test('selection never mixes batches', () => {
  expect(workspaceStudents(roster, 'Existing B', 'group1').map(s => s.id)).toEqual(['e']);
});
