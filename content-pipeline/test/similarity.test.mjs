// Test: duplicate/copy detection engine.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  questionFingerprint,
  buildSourceIndex,
  buildBankIndex,
  checkQuestionSimilarity,
  normalizeText,
} from '../src/lib/similarity.mjs';

const SOURCE_FRAGMENT = {
  id: 'frag_1',
  text: 'Section 7 of the Companies Act, 2013 provides that the certificate of incorporation issued by the Registrar shall be conclusive evidence that all the requirements of the Act have been complied with in respect of registration and matters precedent and incidental thereto, and that the association is a company authorised to be registered and duly registered under the Act.'.repeat(3),
};

const question = (prompt, options, extra = {}) => ({
  id: 'adp_q_x_0001',
  prompt,
  options: options.map((t, i) => ({ id: String.fromCharCode(65 + i), text: t })),
  correctOptionId: 'A',
  explanation: 'The certificate of incorporation is conclusive evidence of compliance with registration requirements.',
  ...extra,
});

test('exact-match fingerprint detects identical questions', () => {
  const a = question('Which section makes the certificate of incorporation conclusive evidence?', ['7', '8', '9', '10']);
  const b = question('Which section makes the certificate of incorporation conclusive evidence?', ['7', '8', '9', '10']);
  assert.equal(questionFingerprint(a), questionFingerprint(b));
});

test('exact-match fingerprint is option-order independent', () => {
  const a = question('Which section?', ['7', '8', '9', '10']);
  const b = question('Which section?', ['10', '9', '8', '7']);
  assert.equal(questionFingerprint(a), questionFingerprint(b));
});

test('verbatim source copy is blocked by source similarity', () => {
  const copy = question(
    SOURCE_FRAGMENT.text.slice(0, 220),
    ['Section 7', 'Section 8', 'Section 9', 'Section 10']
  );
  const sourceIndex = buildSourceIndex([SOURCE_FRAGMENT]);
  const check = checkQuestionSimilarity(copy, { sourceIndex, bankIndex: [], flag: 0.75, block: 0.9 });
  assert.equal(check.verdict, 'blocked');
  assert.ok(check.maxSourceSimilarity >= 0.9, `expected >=0.9, got ${check.maxSourceSimilarity}`);
});

test('original question passes clean against sources', () => {
  const original = question(
    'Rohit and Sneha decide to incorporate a private company. Which document evidences that incorporation was duly completed?',
    ['Certificate of incorporation', 'Memorandum of association', 'Articles of association', 'Certificate of commencement'],
    { explanation: 'The certificate of incorporation is conclusive evidence of due registration.' }
  );
  const sourceIndex = buildSourceIndex([SOURCE_FRAGMENT]);
  const check = checkQuestionSimilarity(original, { sourceIndex, bankIndex: [], flag: 0.75, block: 0.9 });
  assert.equal(check.verdict, 'clean', JSON.stringify(check));
});

test('near-duplicate bank questions are flagged', () => {
  const a = question('What is the time limit for filing a charge with the ROC?', ['30 days', '60 days', '90 days', '120 days'], {
    explanation: 'A charge must be filed within thirty days of creation, with condonation possible.',
  });
  const b = { ...a, id: 'adp_q_x_0002' };
  const bankIndex = buildBankIndex([a]);
  const check = checkQuestionSimilarity(b, { sourceIndex: [], bankIndex, flag: 0.75, block: 0.9 });
  assert.equal(check.verdict, 'blocked');
  assert.ok(check.results.some((r) => r.exact));
});

test('distinct questions in same chapter are clean', () => {
  const a = question('Which form is filed for incorporation of a company?', ['SPICe+', 'Form 5', 'Form 8', 'Form 11']);
  const b = question('Which resolution requires special majority under section 114?', ['75% majority', 'Simple majority', 'Unanimous consent', 'Two-thirds majority']);
  const bankIndex = buildBankIndex([a]);
  const check = checkQuestionSimilarity(b, { sourceIndex: [], bankIndex, flag: 0.75, block: 0.9 });
  assert.equal(check.verdict, 'clean', JSON.stringify(check.results));
});

test('normalizeText lowercases and strips punctuation', () => {
  assert.equal(normalizeText('The Companies Act, 2013 — Section 7!'), 'the companies act 2013 - section 7');
});
