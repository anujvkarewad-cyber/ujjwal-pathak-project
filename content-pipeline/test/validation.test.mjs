// Test: content validation invariants (stage 7).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateQuestionContent,
  validateScenarioContent,
  validateChapterCounts,
} from '../src/lib/validation.mjs';

const CATALOG = {
  chapterId: 'ch-law-03',
  chapterTitle: 'Companies Act, 2013 — Incorporation',
};

const validQuestion = (overrides = {}) => ({
  id: 'adp_q_ch-law-03_0001',
  revision: 1,
  chapterId: 'ch-law-03',
  subject: 'Law',
  paper: 'Paper 2',
  section: 'Business Laws',
  module: 'Module 2',
  chapterNumber: 3,
  chapterTitle: 'Companies Act, 2013 — Incorporation',
  questionType: 'mcq',
  difficulty: 'moderate',
  conceptTags: ['incorporation'],
  prompt: 'Which document is conclusive evidence of due incorporation of a company?',
  options: [
    { id: 'A', text: 'Certificate of incorporation' },
    { id: 'B', text: 'Memorandum of association' },
    { id: 'C', text: 'Articles of association' },
    { id: 'D', text: 'Certificate of commencement' },
  ],
  correctOptionId: 'A',
  explanation: 'Section 7 of the Companies Act, 2013 makes the certificate of incorporation conclusive evidence of compliance.',
  icaiSourceRefs: [{ source: 'module', module: 'Module 2', chapter: 3, section: '3.2', provision: 's.7', edition: 'May 2026' }],
  calibrationRefs: [{ source: 'PYQ', attempt: 'May 2024', questionRef: 'Q1(a)' }],
  scenario: null,
  attemptSpecificRisk: false,
  ...overrides,
});

test('valid question passes with no errors', () => {
  const { errors, warnings } = validateQuestionContent(validQuestion(), { catalogChapter: CATALOG });
  assert.deepEqual(errors, []);
  assert.deepEqual(warnings, []);
});

test('missing ICAI module ref is an error', () => {
  const { errors } = validateQuestionContent(validQuestion({ icaiSourceRefs: [] }), { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('missing ICAI')));
});

test('missing calibration ref is an error', () => {
  const { errors } = validateQuestionContent(validQuestion({ calibrationRefs: [] }), { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('calibration reference')));
});

test('wrong number of options is an error', () => {
  const { errors } = validateQuestionContent(validQuestion({ options: validQuestion().options.slice(0, 3) }), { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('expected 4 options')));
});

test('duplicate options are an error', () => {
  const base = validQuestion();
  base.options[1].text = base.options[0].text;
  const { errors } = validateQuestionContent(base, { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('not pairwise distinct')));
});

test('correctOptionId must reference an option', () => {
  const { errors } = validateQuestionContent(validQuestion({ correctOptionId: 'Z' }), { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('does not match any option id')));
});

test('chapter mismatch is an error', () => {
  const { errors } = validateQuestionContent(validQuestion({ chapterId: 'ch-other' }), { catalogChapter: CATALOG });
  assert.ok(errors.some((e) => e.includes('does not match catalog chapter')));
});

test('scenario_mcq requires linkage with blockTotal 4 and seq 1-4', () => {
  const noLink = validQuestion({ questionType: 'scenario_mcq', scenario: null });
  const badTotal = validQuestion({ questionType: 'scenario_mcq', scenario: { scenarioId: 'adp_s_x_01', seq: 1, blockTotal: 3 } });
  const badSeq = validQuestion({ questionType: 'scenario_mcq', scenario: { scenarioId: 'adp_s_x_01', seq: 5, blockTotal: 4 } });
  assert.ok(validateQuestionContent(noLink, { catalogChapter: CATALOG }).errors.some((e) => e.includes('missing scenario linkage')));
  assert.ok(validateQuestionContent(badTotal, { catalogChapter: CATALOG }).errors.some((e) => e.includes('blockTotal must be 4')));
  assert.ok(validateQuestionContent(badSeq, { catalogChapter: CATALOG }).errors.some((e) => e.includes('seq must be 1-4')));
});

test('attempt-specific risk produces a warning (not error)', () => {
  const { errors, warnings } = validateQuestionContent(validQuestion({ attemptSpecificRisk: true }), { catalogChapter: CATALOG });
  assert.deepEqual(errors, []);
  assert.ok(warnings.some((w) => w.includes('attempt-specific')));
});

test('AI artifact patterns are blocked', () => {
  const { errors } = validateQuestionContent(
    validQuestion({ explanation: 'As an AI language model, I cannot answer this.' }),
    { catalogChapter: CATALOG }
  );
  assert.ok(errors.some((e) => e.includes('generation artifact')));
});

test('scenario validation enforces exactly 4 linked questions', () => {
  const scenario = {
    scenarioId: 'adp_s_ch-law-03_01',
    chapterId: 'ch-law-03',
    passage: 'A group of five promoters decided to incorporate a private limited company in Pune. They drafted the memorandum and articles, filed SPICe+ with the ROC and received approval.',
    icaiSourceRefs: [{ source: 'module', module: 'Module 2', chapter: 3 }],
    calibrationRefs: [{ source: 'MTP', attempt: 'May 2026' }],
    questionIds: ['q1', 'q2', 'q3'],
  };
  const { errors } = validateScenarioContent(scenario, { chapterId: 'ch-law-03' });
  assert.ok(errors.some((e) => e.includes('exactly 4')));
});

test('chapter counts fail closed on wrong totals', () => {
  const chapter = { plainQuestions: [validQuestion()], scenarios: [] };
  const { errors } = validateChapterCounts(chapter, { plain: 30, scenarios: 5, perScenario: 4 });
  assert.ok(errors.some((e) => e.includes('expected 30 plain MCQs')));
  assert.ok(errors.some((e) => e.includes('expected 5 scenarios')));
});
