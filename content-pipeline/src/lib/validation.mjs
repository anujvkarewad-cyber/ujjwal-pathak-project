// Content validation invariants (stage 7, §5.3 of the design).
// Every check returns { errors: [], warnings: [] }. Errors block review and
// publishing; warnings must be acknowledged by the mentor before publish.

import { normalizeText } from './similarity.mjs';

const BLOCKED_PATTERNS = [
  /as\s+an\s+ai\b/i,
  /i\s+cannot\b/i,
  /as\s+a\s+language\s+model\b/i,
  /\(\s*insert\s+[^)]*\)/i,
  /lorem\s+ipsum/i,
  /\[(placeholder|todo|tbd|xxx)\]/i,
];

export function validateQuestionContent(q, { catalogChapter } = {}) {
  const errors = [];
  const warnings = [];

  // Identity & catalog mapping
  if (catalogChapter && q.chapterId !== catalogChapter.chapterId) {
    errors.push(`chapterId ${q.chapterId} does not match catalog chapter ${catalogChapter.chapterId}`);
  }
  if (catalogChapter && q.chapterTitle !== catalogChapter.chapterTitle) {
    warnings.push(`chapterTitle "${q.chapterTitle}" differs from catalog "${catalogChapter.chapterTitle}"`);
  }

  // Options
  const opts = q.options || [];
  if (opts.length !== 4) errors.push(`expected 4 options, got ${opts.length}`);
  const texts = opts.map((o) => normalizeText(o?.text || ''));
  if (texts.some((t) => t.length === 0)) errors.push('at least one option is empty');
  if (new Set(texts).size !== texts.length) errors.push('options are not pairwise distinct');
  const ids = opts.map((o) => String(o?.id || ''));
  if (new Set(ids).size !== ids.length) errors.push('option ids are not unique');
  if (!ids.includes(String(q.correctOptionId))) {
    errors.push(`correctOptionId "${q.correctOptionId}" does not match any option id`);
  }
  const promptNorm = normalizeText(q.prompt || '');
  for (const t of texts) {
    if (t === promptNorm) {
      errors.push('an option duplicates the prompt verbatim');
      break;
    }
  }

  // Prompt / explanation sanity
  if ((q.prompt || '').trim().length < 10) errors.push('prompt too short');
  if ((q.explanation || '').trim().length < 10) errors.push('explanation too short');
  for (const pattern of BLOCKED_PATTERNS) {
    if (pattern.test(`${q.prompt} ${q.explanation} ${texts.join(' ')}`)) {
      errors.push(`generation artifact detected: ${pattern}`);
    }
  }

  // References
  if (!Array.isArray(q.icaiSourceRefs) || q.icaiSourceRefs.length === 0) {
    errors.push('missing ICAI module source reference(s)');
  }
  if (!Array.isArray(q.calibrationRefs) || q.calibrationRefs.length === 0) {
    errors.push('missing RTP/MTP/PYQ calibration reference(s)');
  }
  for (const ref of q.icaiSourceRefs || []) {
    if (!ref || !ref.source || String(ref.source).toLowerCase() !== 'module') {
      errors.push('icaiSourceRefs must reference the ICAI module (source: "module")');
    }
  }
  for (const ref of q.calibrationRefs || []) {
    if (!ref || !['RTP', 'MTP', 'PYQ'].includes(String(ref.source))) {
      errors.push('calibrationRefs must reference RTP/MTP/PYQ sources');
    }
  }

  // Type-specific
  if (q.questionType === 'scenario_mcq') {
    if (!q.scenario || !q.scenario.scenarioId) {
      errors.push('scenario_mcq missing scenario linkage');
    } else if (q.scenario.blockTotal !== 4) {
      errors.push(`scenario_mcq blockTotal must be 4, got ${q.scenario.blockTotal}`);
    } else if (!Number.isInteger(q.scenario.seq) || q.scenario.seq < 1 || q.scenario.seq > 4) {
      errors.push(`scenario seq must be 1-4, got ${q.scenario.seq}`);
    }
  } else if (q.questionType === 'mcq' && q.scenario != null) {
    errors.push('plain mcq must have scenario: null');
  }

  // Concept tags
  if (!Array.isArray(q.conceptTags) || q.conceptTags.length === 0) {
    errors.push('at least one conceptTag is required');
  }

  // Attempt-specific legal/tax risk
  if (q.attemptSpecificRisk === true) {
    warnings.push('attempt-specific legal/tax content flagged — mentor confirmation required before publish');
  }

  return { errors, warnings };
}

export function validateScenarioContent(scenario, { chapterId, expectedQuestionIds } = {}) {
  const errors = [];
  const warnings = [];

  if (chapterId && scenario.chapterId !== chapterId) {
    errors.push(`scenario chapterId ${scenario.chapterId} does not match chapter ${chapterId}`);
  }
  const ids = scenario.questionIds || [];
  if (ids.length !== 4) errors.push(`scenario must link exactly 4 questions, got ${ids.length}`);
  if (new Set(ids).size !== ids.length) errors.push('scenario questionIds are not unique');
  if (expectedQuestionIds && JSON.stringify([...ids].sort()) !== JSON.stringify([...expectedQuestionIds].sort())) {
    errors.push('scenario questionIds do not match the linked question records');
  }
  if ((scenario.passage || '').trim().length < 40) errors.push('scenario passage too short');
  if (!Array.isArray(scenario.icaiSourceRefs) || scenario.icaiSourceRefs.length === 0) {
    errors.push('scenario missing ICAI module source reference(s)');
  }
  if (!Array.isArray(scenario.calibrationRefs) || scenario.calibrationRefs.length === 0) {
    errors.push('scenario missing RTP/MTP/PYQ calibration reference(s)');
  }
  if (scenario.attemptSpecificRisk === true) {
    warnings.push('attempt-specific legal/tax content flagged — mentor confirmation required before publish');
  }
  return { errors, warnings };
}

export function validateChapterCounts(chapter, { plain = 30, scenarios = 5, perScenario = 4 } = {}) {
  const errors = [];
  const warnings = [];
  const plainQs = (chapter.plainQuestions || []).filter((q) => q.questionType === 'mcq');
  const scenariosArr = chapter.scenarios || [];
  const scenarioQs = scenariosArr.flatMap((s) => s.questions || []).filter((q) => q.questionType === 'scenario_mcq');

  if (plainQs.length !== plain) errors.push(`expected ${plain} plain MCQs, found ${plainQs.length}`);
  if (scenariosArr.length !== scenarios) errors.push(`expected ${scenarios} scenarios, found ${scenariosArr.length}`);
  if (scenarioQs.length !== scenarios * perScenario) {
    errors.push(`expected ${scenarios * perScenario} scenario MCQs, found ${scenarioQs.length}`);
  }

  // Every scenario question must belong to a scenario block in this chapter.
  const linkedIds = new Set(scenariosArr.flatMap((s) => s.questionIds || []));
  for (const q of scenarioQs) {
    if (!q.scenario || !linkedIds.has(q.id)) {
      errors.push(`scenario_mcq ${q.id} is not linked from any scenario block`);
    }
  }
  // Every linked id must exist among questions, with correct seq 1..4.
  for (const s of scenariosArr) {
    const blockIds = s.questionIds || [];
    const seqs = new Set();
    for (const qid of blockIds) {
      const q = scenarioQs.find((x) => x.id === qid);
      if (!q) {
        errors.push(`scenario ${s.scenarioId} links missing question ${qid}`);
        continue;
      }
      if (q.scenario.scenarioId !== s.scenarioId) {
        errors.push(`question ${qid} scenarioId mismatch`);
      }
      seqs.add(q.scenario.seq);
    }
    if (blockIds.length === 4 && (seqs.size !== 4 || [...seqs].some((n) => n < 1 || n > 4))) {
      errors.push(`scenario ${s.scenarioId} must have questions with seq 1..4`);
    }
  }
  return { errors, warnings };
}
