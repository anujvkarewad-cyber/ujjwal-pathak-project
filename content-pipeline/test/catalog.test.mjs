// Test: catalog authority — TS parsing, normalization, count enforcement.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parseTsArrayLiteral, expandChapterGroups, groupFromPaper, normalizeChapterEntry, loadCatalog } from '../src/lib/catalog.mjs';

const TS_FIXTURE = `
// Official ICAI chapter catalog — generated file. DO NOT EDIT.
export const icaiChapterCatalog = [
  {
    chapterId: 'ch-acc-01',
    subject: 'Advanced Accounting',
    paper: 'Paper 1',
    section: 'Accounting Standards',
    module: 'Module 1',
    chapterNumber: 1,
    chapterTitle: 'Introduction to Accounting Standards',
    group: 'Group 1',
    learningPoints: ['framework', 'applicability'],
  },
  {
    chapterId: 'ch-law-03',
    subject: 'Law',
    paper: 'Paper 2',
    section: 'Business Laws',
    module: 'Module 2',
    chapterNumber: 3,
    chapterTitle: 'Companies Act, 2013 — Incorporation',
    group: 'Group 1',
    learningPoints: ['incorporation', 'certificate of incorporation'],
  },
] as const;
`;

test('parseTsArrayLiteral extracts the exported array from TS', () => {
  const parsed = parseTsArrayLiteral(TS_FIXTURE);
  assert.ok(Array.isArray(parsed));
  assert.equal(parsed.length, 2);
  assert.equal(parsed[0].chapterId, 'ch-acc-01');
});

test('normalizeChapterEntry maps fields to the canonical shape', () => {
  const entry = normalizeChapterEntry({
    chapterId: 'ch-acc-01',
    subject: 'Advanced Accounting',
    paper: 'Paper 1',
    section: 'Accounting Standards',
    module: 'Module 1',
    chapterNumber: 1,
    chapterTitle: 'Introduction to Accounting Standards',
    group: 'Group 1',
    learningPoints: ['framework'],
  });
  assert.deepEqual(entry, {
    chapterId: 'ch-acc-01',
    subject: 'Advanced Accounting',
    paper: 'Paper 1',
    section: 'Accounting Standards',
    module: 'Module 1',
    chapterNumber: 1,
    chapterTitle: 'Introduction to Accounting Standards',
    group: 'Group 1',
    learningPoints: ['framework'],
  });
});

test('invalid entries are rejected', () => {
  assert.equal(normalizeChapterEntry({}), null);
  assert.equal(normalizeChapterEntry({ chapterId: 'x' }), null);
});

test('loadCatalog parses a TS file directly', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
  const ts = path.join(dir, 'catalog.ts');
  fs.writeFileSync(ts, TS_FIXTURE);
  const catalog = loadCatalog({ tsPath: ts, expectedCount: 2 });
  assert.equal(catalog.count, 2);
});

test('loadCatalog fails closed on chapter-count mismatch', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
  const ts = path.join(dir, 'catalog.ts');
  fs.writeFileSync(ts, TS_FIXTURE);
  assert.throws(() => loadCatalog({ tsPath: ts, expectedCount: 94 }), /Refusing to continue/);
});

test('loadCatalog fails closed on duplicate chapterIds', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
  const snap = path.join(dir, 'chapters.json');
  fs.writeFileSync(
    snap,
    JSON.stringify({
      chapters: [
        { chapterId: 'a', chapterNumber: 1, chapterTitle: 'One' },
        { chapterId: 'a', chapterNumber: 2, chapterTitle: 'Two' },
      ],
    })
  );
  assert.throws(() => loadCatalog({ snapshotPath: snap, expectedCount: 2 }), /duplicate chapterIds/);
});

test('loadCatalog accepts a JSON snapshot', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
  const snap = path.join(dir, 'chapters.json');
  fs.writeFileSync(
    snap,
    JSON.stringify({
      chapters: [
        { chapterId: 'a', chapterNumber: 1, chapterTitle: 'One' },
        { chapterId: 'b', chapterNumber: 2, chapterTitle: 'Two' },
      ],
    })
  );
  const catalog = loadCatalog({ snapshotPath: snap, expectedCount: 2 });
  assert.equal(catalog.count, 2);
  assert.equal(catalog.chapters[0].chapterId, 'a');
});

// ── Real icaiChapterCatalog.ts structure (chapterGroups expansion) ──────────
const REAL_SHAPE_FIXTURE = `
type ChapterGroup = { idPrefix: string; subject: string; paper: string; section?: string; module: string; chapters: Array<[number, string]> };
const chapterGroups: ChapterGroup[] = [
  {
    idPrefix: 'advanced-accounting',
    subject: 'Accounts',
    paper: 'Paper 1: Advanced Accounting',
    module: 'Module 1',
    chapters: [
      [1, 'Introduction to Accounting Standards'],
      [2, 'Framework for Preparation and Presentation of Financial Statements'],
    ],
  },
  {
    idPrefix: 'costing',
    subject: 'Costing',
    paper: 'Paper 4: Cost and Management Accounting',
    section: 'Cost and Management Accounting',
    module: 'Paper 4',
    chapters: [
      [14, 'Marginal Costing'],
    ],
  },
];
export const officialMcqChapterCatalog = chapterGroups
  .flatMap((group) => group.chapters.map(([chapterNumber, title]) => ({ id: \`\${group.idPrefix}-\${chapterNumber}\`, ...group, chapterNumber, title })));
`;

test('real-file chapterGroups shape is parsed and expanded', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'catalog-'));
  const ts = path.join(dir, 'icaiChapterCatalog.ts');
  fs.writeFileSync(ts, REAL_SHAPE_FIXTURE);
  const catalog = loadCatalog({ tsPath: ts, expectedCount: 3 });
  assert.equal(catalog.count, 3);
  assert.equal(catalog.chapters[0].chapterId, 'advanced-accounting-1');
  assert.equal(catalog.chapters[2].chapterId, 'costing-14');
  assert.equal(catalog.chapters[2].chapterTitle, 'Marginal Costing');
});

test('group is derived from paper number when not explicit', () => {
  assert.equal(groupFromPaper('Paper 1: Advanced Accounting'), 'Group 1');
  assert.equal(groupFromPaper('Paper 4: Cost and Management Accounting'), 'Group 2');
  assert.equal(groupFromPaper('no paper'), '');
  const entry = normalizeChapterEntry({
    id: 'costing-14', subject: 'Costing', paper: 'Paper 4: Cost and Management Accounting',
    module: 'Paper 4', chapterNumber: 14, title: 'Marginal Costing',
  });
  assert.equal(entry.group, 'Group 2');
});
