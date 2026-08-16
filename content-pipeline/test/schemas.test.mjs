// Test: JSON Schema validation (stage 6) against a canonical sample.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import Ajv from 'ajv';
import { questionSchema, scenarioSchema, manifestSchema } from '../src/lib/schemas.mjs';

const ajv = new Ajv({ allErrors: true, strict: false });

const validQuestion = {
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
  prompt: 'Which document is conclusive evidence of due incorporation?',
  options: [
    { id: 'A', text: 'Certificate of incorporation' },
    { id: 'B', text: 'Memorandum of association' },
    { id: 'C', text: 'Articles of association' },
    { id: 'D', text: 'Certificate of commencement' },
  ],
  correctOptionId: 'A',
  explanation: 'Section 7 makes the certificate conclusive evidence.',
  icaiSourceRefs: [{ source: 'module', module: 'Module 2', chapter: 3, section: '3.2' }],
  calibrationRefs: [{ source: 'PYQ', attempt: 'May 2024' }],
  generationMeta: { model: 'test', promptVersion: '1.0.0', generatedAt: '2026-08-16T00:00:00Z' },
  scenario: null,
  status: 'generated',
  statusHistory: [{ from: null, to: 'generated', by: 'pipeline', at: '2026-08-16T00:00:00Z' }],
};

const validScenario = {
  scenarioId: 'adp_s_ch-law-03_01',
  revision: 1,
  chapterId: 'ch-law-03',
  passage: 'A group of five promoters decided to incorporate a private limited company in Pune. They prepared the memorandum and articles, filed SPICe+ with the Registrar and sought approval.',
  icaiSourceRefs: [{ source: 'module', module: 'Module 2', chapter: 3 }],
  calibrationRefs: [{ source: 'MTP', attempt: 'May 2026' }],
  questionIds: ['adp_q_ch-law-03_0031', 'adp_q_ch-law-03_0032', 'adp_q_ch-law-03_0033', 'adp_q_ch-law-03_0034'],
  status: 'generated',
  statusHistory: [{ from: null, to: 'generated', by: 'pipeline', at: '2026-08-16T00:00:00Z' }],
};

test('question schema accepts a valid question', () => {
  const ok = ajv.validate(questionSchema, validQuestion);
  assert.ok(ok, JSON.stringify(ajv.errors));
});

test('question schema rejects <4 options', () => {
  const bad = { ...validQuestion, options: validQuestion.options.slice(0, 3) };
  assert.equal(ajv.validate(questionSchema, bad), false);
});

test('question schema rejects unknown difficulty', () => {
  const bad = { ...validQuestion, difficulty: 'extreme' };
  assert.equal(ajv.validate(questionSchema, bad), false);
});

test('question schema rejects non-adp id pattern', () => {
  const bad = { ...validQuestion, id: 'q1' };
  assert.equal(ajv.validate(questionSchema, bad), false);
});

test('scenario schema requires exactly 4 questionIds', () => {
  assert.ok(ajv.validate(scenarioSchema, validScenario));
  const bad = { ...validScenario, questionIds: validScenario.questionIds.slice(0, 3) };
  assert.equal(ajv.validate(scenarioSchema, bad), false);
});

test('manifest schema validates a well-formed manifest', () => {
  const manifest = {
    schemaVersion: 1,
    revision: 7,
    publishedAt: '2026-08-16T00:00:00Z',
    publishedBy: 'mentor@example.com',
    catalogRevision: 'may-2026',
    chapters: [{
      chapterId: 'ch-law-03',
      counts: { plain: 30, scenarios: 5, scenarioMcqs: 20, total: 50 },
      questionIds: ['adp_q_ch-law-03_0001'],
      chunkWeb: 'chunks/ch-law-03.r7.abc.json',
      chunkMobile: 'chunks/m/ch-law-03.r7.abc.json',
      contentHash: 'sha256:abc123',
    }],
    dailyMcqFrozen: { learningDataHash: 'sha256:xyz' },
  };
  assert.ok(ajv.validate(manifestSchema, manifest), JSON.stringify(ajv.errors));
  const bad = { ...manifest, revision: 'seven' };
  assert.equal(ajv.validate(manifestSchema, bad), false);
});
