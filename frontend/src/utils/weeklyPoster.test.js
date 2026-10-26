import { boardLines, buildPosterSvg, esc, posterCaption, weekLabel } from './weeklyPoster';

// The card that gets posted into a students' WhatsApp group. These are the
// failures that would be embarrassing in public, not cosmetics.

const BOARD = {
  batch: 'Before Result Batch 1',
  group: 'Group 1',
  weekStart: '2026-10-11',
  weekEnd: '2026-10-17',
  studentCount: 36,
  top3: [
    { place: 1, studentId: 'UMP0073', studentName: 'Harpreet', hours: 99.5 },
    { place: 2, studentId: 'UMP0063', studentName: 'Nitin Yadav', hours: 71.3 },
    { place: 3, studentId: 'UMP0065', studentName: 'Siddhi Gaikwad', hours: 56.6 },
  ],
};

describe('boardLines - the corner tag', () => {
  test.each([
    ['Group 1', 'GROUP 1'],
    ['group 2', 'GROUP 2'],
    ['Both', 'BOTH GROUPS'],
    ['Both Groups', 'BOTH GROUPS'],
    ['(no group set)', 'GROUP NOT SET'],
    ['', 'BOTH GROUPS'],
  ])('sheet value %p prints as %p', (group, expected) => {
    expect(boardLines('Before Result Batch 1', group)[1]).toBe(expected);
  });

  test('batch number comes from the batch name, so the tag is never invented', () => {
    expect(boardLines('Before Result Batch 2', 'Group 1')[0]).toBe('BATCH 2');
    expect(boardLines('', 'Group 1')[0]).toBe('BATCH');
  });
});

describe('buildPosterSvg', () => {
  test('shows all three names, in place order, with hours to one decimal', () => {
    const svg = buildPosterSvg(BOARD);
    const at = (n) => svg.indexOf(n);
    // drawn left-to-right as 2nd, 1st, 3rd — and each name must ride directly
    // above its own hours plate, which is the only way a wrong pairing gets caught
    expect(at('NITIN YADAV')).toBeLessThan(at('71.3'));
    expect(at('71.3')).toBeLessThan(at('HARPREET'));
    expect(at('HARPREET')).toBeLessThan(at('99.5'));
    expect(at('99.5')).toBeLessThan(at('SIDDHI GAIKWAD'));
    expect(at('SIDDHI GAIKWAD')).toBeLessThan(at('56.6'));
  });

  test('a name that would overflow its ribbon is clamped, and the ribbon still sizes to the plate', () => {
    const svg = buildPosterSvg({
      ...BOARD,
      top3: [{ place: 1, studentName: 'Aishwariya Gupta Sharma Verma', hours: 12 }],
    });
    expect(svg).toContain('AISHWARIYA GUPTA…');   // cut at a word, not mid-name
    expect(svg).not.toContain('SHARMA');
    // every drawn name rides on a textLength, so no renderer can spill it out
    expect(svg).toMatch(/lengthAdjust="spacingAndGlyphs"[^>]*>AISHWARIYA/);
  });

  test('escapes a name instead of letting it inject markup into the mentor dashboard', () => {
    const svg = buildPosterSvg({ ...BOARD, top3: [{ place: 1, studentName: '<img src=x onerror=alert(1)>', hours: 3 }] });
    expect(svg).not.toContain('<img');
    expect(svg).toContain('&lt;');
    expect(esc('a & b "c" <d>')).toBe('a &amp; b &quot;c&quot; &lt;d&gt;');
  });

  test('a missing place or a missing score never prints undefined or NaN', () => {
    const svg = buildPosterSvg({ ...BOARD, top3: [{ place: 1, studentName: 'Only One', hours: undefined }] });
    expect(svg).not.toMatch(/undefined/);
    expect(svg).not.toMatch(/NaN/);
    expect(svg).toContain('>—<');       // empty 2nd and 3rd slots
    expect(svg).toContain('0.0');        // hours that were never sent
  });

  test('the week is on the card, so an old screenshot cannot be mistaken for this week', () => {
    expect(buildPosterSvg(BOARD)).toContain('WEEK 11–17 Oct 2026');
  });

  test('an empty board still returns a card the UI can render', () => {
    expect(buildPosterSvg({})).toMatch(/^<svg[\s\S]*<\/svg>$/);
    expect(buildPosterSvg()).toMatch(/^<svg/);
  });
});

describe('weekLabel', () => {
  test('same-month weeks collapse the left month', () => {
    expect(weekLabel('2026-10-11', '2026-10-17')).toBe('11–17 Oct 2026');
  });

  test('month-crossing weeks name both months', () => {
    expect(weekLabel('2026-10-26', '2026-11-01')).toBe('26 Oct–1 Nov 2026');
  });

  test('garbage in, blank out - never "Invalid Date" on a public card', () => {
    expect(weekLabel('', null)).toBe('');
    expect(weekLabel('not a date', '2026-10-17')).toBe('');
  });
});

describe('posterCaption', () => {
  test('the text under the image carries the board, the week and the three medals', () => {
    const caption = posterCaption(BOARD);
    expect(caption).toContain('BATCH 1 · GROUP 1 · 11–17 Oct 2026');
    expect(caption.indexOf('🥇 Harpreet')).toBeLessThan(caption.indexOf('🥈 Nitin Yadav'));
    expect(caption.indexOf('🥈 Nitin Yadav')).toBeLessThan(caption.indexOf('🥉 Siddhi Gaikwad'));
    expect(caption).toContain('99.5 hrs');
    expect(caption).toContain('Daily submission aapki zimmedari hai');   // the owner's 18-Oct line
    expect(caption.trim().endsWith('Keep it Up!')).toBe(true);           // and it still closes on the brand
  });

  test('places sort themselves, whatever order the endpoint sent', () => {
    const caption = posterCaption({ ...BOARD, top3: [BOARD.top3[2], BOARD.top3[0], BOARD.top3[1]] });
    expect(caption.indexOf('🥇')).toBeLessThan(caption.indexOf('🥈'));
    expect(caption.indexOf('🥈')).toBeLessThan(caption.indexOf('🥉'));
  });
});
