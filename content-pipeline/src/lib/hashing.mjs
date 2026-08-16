// Deterministic hashing + canonical JSON serialization.
// The canonical form is the single representation used for all content hashes
// (manifest `contentHash`, duplicate detection, cross-build comparison).
import crypto from 'node:crypto';
import fs from 'node:fs';

const CONTENT_KEYS = [
  'id', 'revision', 'chapterId', 'subject', 'paper', 'section', 'module',
  'chapterNumber', 'chapterTitle', 'questionType', 'difficulty', 'conceptTags',
  'prompt', 'options', 'correctOptionId', 'explanation', 'icaiSourceRefs',
  'calibrationRefs', 'scenario',
];

export function canonicalQuestion(q) {
  const out = {};
  for (const k of CONTENT_KEYS) {
    if (q[k] !== undefined && q[k] !== null) out[k] = q[k];
  }
  // options: sort by option id so option order can never change the hash
  if (Array.isArray(out.options)) {
    out.options = [...out.options].sort((a, b) => String(a.id).localeCompare(String(b.id)));
  }
  if (out.conceptTags) out.conceptTags = [...out.conceptTags].sort();
  if (out.scenario) {
    out.scenario = {
      scenarioId: out.scenario.scenarioId,
      seq: out.scenario.seq,
      blockTotal: out.scenario.blockTotal,
    };
  }
  return out;
}

export function canonicalScenario(s) {
  return {
    scenarioId: s.scenarioId,
    revision: s.revision,
    chapterId: s.chapterId,
    passage: s.passage,
    icaiSourceRefs: s.icaiSourceRefs || [],
    calibrationRefs: s.calibrationRefs || [],
    questionIds: [...(s.questionIds || [])],
  };
}

export function canonicalChapter(c) {
  return {
    chapterId: c.chapterId,
    chapterTitle: c.chapterTitle,
    subject: c.subject,
    group: c.group,
    plainQuestions: (c.plainQuestions || []).map(canonicalQuestion),
    scenarios: (c.scenarios || []).map((s) => ({
      ...canonicalScenario(s),
      questions: (s.questions || []).map(canonicalQuestion),
    })),
  };
}

export function canonicalJson(value) {
  return JSON.stringify(value, stableReplacer, 2);
}

function stableReplacer(key, value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return value;
  const sorted = {};
  for (const k of Object.keys(value).sort()) sorted[k] = value[k];
  return sorted;
}

export function sha256Hex(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

export function contentHashOf(value) {
  return `sha256:${sha256Hex(canonicalJson(value))}`;
}

export function hashFile(filePath) {
  const h = crypto.createHash('sha256');
  h.update(fs.readFileSync(filePath));
  return h.digest('hex');
}
