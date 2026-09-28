import { matchesStudentGroup, normalizeStudentGroup, TRACKER_GROUP_FILTERS } from './studentGroup';

describe('daily tracker student-group filters', () => {
  test.each([
    ['Group 1', 'group1'],
    ['Group I', 'group1'],
    ['G1', 'group1'],
    ['Group 2', 'group2'],
    ['Group II', 'group2'],
    ['G2', 'group2'],
    ['Both Groups', 'both'],
    ['Group I & Group II', 'both'],
    ['Group 1 + Group 2', 'both'],
    ['', 'unknown'],
    ['Unassigned', 'unknown'],
  ])('normalizes %s', (input, expected) => {
    expect(normalizeStudentGroup(input)).toBe(expected);
  });

  test('Both Groups is a strict group, not a wildcard', () => {
    expect(matchesStudentGroup('Both Groups', 'Both Groups')).toBe(true);
    expect(matchesStudentGroup('Group 1', 'Both Groups')).toBe(false);
    expect(matchesStudentGroup('Group 2', 'Both Groups')).toBe(false);
  });

  test('All Groups is the only wildcard', () => {
    expect(TRACKER_GROUP_FILTERS).toEqual(['All Groups', 'Group 1', 'Group 2', 'Both Groups']);
    expect(matchesStudentGroup('Group 1', 'All Groups')).toBe(true);
    expect(matchesStudentGroup('Group 2', 'All Groups')).toBe(true);
    expect(matchesStudentGroup('Both Groups', 'All Groups')).toBe(true);
    expect(matchesStudentGroup('', 'All Groups')).toBe(true);
  });
});
