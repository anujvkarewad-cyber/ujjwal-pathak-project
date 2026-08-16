// Test: canonical hashing — deterministic across option order and key order.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalQuestion, contentHashOf } from '../src/lib/hashing.mjs';

const q = {
  id: 'adp_q_ch-law-03_0001',
  revision: 1,
  chapterId: 'ch-law-03',
  prompt: 'Which provision governs the issue of the certificate of incorporation?',
  options: [
    { id: 'A', text: 'Section 7' },
    { id: 'B', text: 'Section 8' },
    { id: 'C', text: 'Section 9' },
    { id: 'D', text: 'Section 10' },
  ],
  correctOptionId: 'A',
  explanation: 'Under the Companies Act, 2013, section 7 deals with incorporation.',
  conceptTags: ['incorporation', 'certificate'],
};

test('canonical hash is stable across option order', () => {
  const shuffled = {
    ...q,
    options: [q.options[3], q.options[0], q.options[2], q.options[1]],
  };
  assert.equal(contentHashOf(canonicalQuestion(q)), contentHashOf(canonicalQuestion(shuffled)));
});

test('canonical hash changes when content changes', () => {
  const changed = { ...q, correctOptionId: 'B' };
  assert.notEqual(contentHashOf(canonicalQuestion(q)), contentHashOf(canonicalQuestion(changed)));
});
