// Stage 5 — Chapter-wise AI generation.
// For each chapter: 30 plain MCQs + 5 case scenarios (4 linked MCQs each).
// Pipeline assigns ALL ids/sequences deterministically; the model only fills
// content. Resumable, bounded retries, dry-run cost estimate, and a hard
// fail-closed rule: blocked chapters (no module source) are never generated.

import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir, fail } from './lib/config.mjs';
import { isMain } from './lib/main.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { loadJob, saveJob, jobDir } from './lib/jobs.mjs';
import { getAdapter } from './ai/adapters.mjs';
import { SYSTEM_PROMPT, plainMcqPrompt, scenarioPrompt } from './ai/prompts.mjs';

const PROMPT_VERSION = '1.0.0';
const DIFFICULTY_ROTATION = ['moderate', 'easy', 'moderate', 'hard', 'moderate'];

function resolveArgs(argv) {
  const args = { chapter: null, dryRun: false, selfCheck: false };
  for (const a of argv) {
    if (a.startsWith('--chapter=')) args.chapter = a.split('=')[1];
    if (a === '--dry-run') args.dryRun = true;
    if (a === '--self-check') args.selfCheck = true;
  }
  return args;
}

function loadMappingFor(chapterId) {
  const p = path.join(config.stateDir, 'mapping.json');
  if (!fs.existsSync(p)) return null;
  const report = JSON.parse(fs.readFileSync(p, 'utf8'));
  return (report.chapters || []).find((c) => c.chapterId === chapterId) || null;
}

function fragmentTexts(ids) {
  const fragPath = path.join(config.stateDir, 'fragments.json');
  if (!fs.existsSync(fragPath) || !ids?.length) return [];
  const fragments = JSON.parse(fs.readFileSync(fragPath, 'utf8'));
  const byId = new Map(fragments.map((f) => [f.id, f]));
  return ids.map((id) => byId.get(id)?.text || '').filter(Boolean);
}

function makeBase(chapter, mapping) {
  return {
    chapterId: chapter.chapterId,
    subject: chapter.subject,
    paper: chapter.paper,
    section: chapter.section,
    module: chapter.module,
    chapterNumber: chapter.chapterNumber,
    chapterTitle: chapter.chapterTitle,
    generationMeta: {
      model: adapterModelName(),
      promptVersion: PROMPT_VERSION,
      generatedAt: new Date().toISOString(),
      sourceDocIds: [
        ...(mapping?.moduleFragmentIds || []),
        ...(mapping?.rtpFragmentIds || []),
        ...(mapping?.mtpFragmentIds || []),
        ...(mapping?.pyqFragmentIds || []),
      ],
      contentRevision: 'may-2026',
    },
    status: 'generated',
    statusHistory: [{ from: null, to: 'generated', by: 'pipeline', at: new Date().toISOString() }],
    validation: { errors: [], warnings: [] },
    attemptSpecificRisk: false,
  };
}

function adapterModelName() {
  const a = getAdapter();
  const names = { openai: config.openai.model, anthropic: config.anthropic.model, gemini: config.gemini.model };
  return names[a.name] || config.aiProvider;
}

async function withRetry(adapter, buildPrompt, label) {
  let lastErr = null;
  for (let attempt = 1; attempt <= config.generationMaxRetries; attempt++) {
    try {
      const out = await adapter.complete({ system: SYSTEM_PROMPT, user: buildPrompt(), json: true });
      return out;
    } catch (e) {
      lastErr = e;
      const waitMs = 1000 * 2 ** (attempt - 1);
      console.warn(`[stage-5] ${label} attempt ${attempt}/${config.generationMaxRetries} failed: ${e.message} — retrying in ${waitMs}ms`);
      await new Promise((r) => setTimeout(r, waitMs));
    }
  }
  throw lastErr || new Error(`${label} failed`);
}

function qid(chapterId, seq) {
  return `adp_q_${chapterId}_${String(seq).padStart(4, '0')}`;
}
function sid(chapterId, seq) {
  return `adp_s_${chapterId}_${String(seq).padStart(2, '0')}`;
}

async function generateChapter(chapter, mapping, { dryRun, selfCheck }) {
  const adapter = getAdapter();
  const plainTarget = config.questionsPlainPerChapter;
  const scenarioTarget = config.scenariosPerChapter;
  const perScenario = config.questionsPerScenario;

  const job = loadJob(chapter.chapterId) || {
    chapterId: chapter.chapterId,
    plainQuestions: [],
    scenarios: [],
  };
  const existingScenarios = job.scenarios.length;

  if (dryRun) {
    const estimate = {
      plainNeeded: Math.max(0, plainTarget - job.plainQuestions.length),
      scenariosNeeded: Math.max(0, scenarioTarget - existingScenarios),
      calls: Math.max(0, plainTarget - job.plainQuestions.length) + Math.max(0, scenarioTarget - existingScenarios),
      note: 'No AI calls made in dry-run. Actual cost depends on provider and context size.',
    };
    console.log(`[stage-5] ${chapter.chapterId} dry-run: ${JSON.stringify(estimate)}`);
    return { chapterId: chapter.chapterId, failures: [], dryRun: true };
  }

  const mappingContext = mapping
    ? {
        moduleFragmentTexts: fragmentTexts(mapping.moduleFragmentIds),
        rtpFragmentTexts: fragmentTexts(mapping.rtpFragmentIds),
        mtpFragmentTexts: fragmentTexts(mapping.mtpFragmentIds),
        pyqFragmentTexts: fragmentTexts(mapping.pyqFragmentIds),
      }
    : null;

  // ── Plain MCQs ──
  let seq = job.plainQuestions.length;
  const failures = [];
  while (seq < plainTarget) {
    const number = seq + 1;
    const difficulty = DIFFICULTY_ROTATION[seq % DIFFICULTY_ROTATION.length];
    const label = `${chapter.chapterId} plain #${number}`;
    const promptFn = () => plainMcqPrompt(chapter, mappingContext, { index: seq, total: plainTarget, difficulty });
    try {
      const raw = await withRetry(adapter, promptFn, label);
      const q = {
        ...makeBase(chapter, mapping),
        id: qid(chapter.chapterId, number),
        revision: 1,
        questionType: 'mcq',
        difficulty,
        prompt: raw.prompt,
        options: raw.options,
        correctOptionId: raw.correctOptionId,
        explanation: raw.explanation,
        conceptTags: raw.conceptTags,
        icaiSourceRefs: raw.icaiSourceRefs,
        calibrationRefs: raw.calibrationRefs,
        attemptSpecificRisk: !!raw.attemptSpecificRisk,
        scenario: null,
      };
      job.plainQuestions.push(q);
      seq++;
    } catch (e) {
      failures.push({ item: label, error: e.message });
      break; // stop this chapter's plain run — report, don't fabricate
    }
  }

  // ── Scenarios ──
  let scenarioSeq = existingScenarios;
  const existingScenarioQ = job.scenarios.reduce((a, s) => a + (s.questions ? s.questions.length : (s.questionIds || []).length), 0);
  let questionSeq = plainTarget + existingScenarioQ;
  while (scenarioSeq < scenarioTarget) {
    const number = scenarioSeq + 1;
    const label = `${chapter.chapterId} scenario #${number}`;
    const promptFn = () => scenarioPrompt(chapter, mappingContext, { index: scenarioSeq, total: scenarioTarget });
    const scenarioId = sid(chapter.chapterId, number);
    const blockQids = Array.from({ length: perScenario }, (_, i) => qid(chapter.chapterId, questionSeq + i + 1));
    try {
      const raw = await withRetry(adapter, promptFn, label);
      const questions = (raw.questions || []).slice(0, perScenario);
      if (questions.length !== perScenario) {
        throw new Error(`scenario returned ${questions.length}/${perScenario} questions`);
      }
      const built = questions.map((rq, i) => ({
        ...makeBase(chapter, mapping),
        id: blockQids[i],
        revision: 1,
        questionType: 'scenario_mcq',
        difficulty: rq.difficulty || (i < 2 ? 'moderate' : 'hard'),
        prompt: rq.prompt,
        options: rq.options,
        correctOptionId: rq.correctOptionId,
        explanation: rq.explanation,
        conceptTags: rq.conceptTags,
        icaiSourceRefs: rq.icaiSourceRefs,
        calibrationRefs: rq.calibrationRefs,
        attemptSpecificRisk: !!rq.attemptSpecificRisk,
        scenario: { scenarioId, seq: i + 1, blockTotal: perScenario },
      }));
      job.scenarios.push({
        scenarioId,
        revision: 1,
        chapterId: chapter.chapterId,
        passage: raw.passage,
        icaiSourceRefs: raw.icaiSourceRefs || [],
        calibrationRefs: raw.calibrationRefs || [],
        attemptSpecificRisk: !!raw.attemptSpecificRisk,
        questionIds: blockQids,
        status: 'generated',
        statusHistory: [{ from: null, to: 'generated', by: 'pipeline', at: new Date().toISOString() }],
        validation: { errors: [], warnings: [] },
        questions: built,
      });
      scenarioSeq++;
      questionSeq += perScenario;
    } catch (e) {
      failures.push({ item: label, error: e.message });
      break;
    }
  }

  saveJob(chapter.chapterId, job);
  fs.writeFileSync(
    path.join(jobDir(chapter.chapterId), 'generation.json'),
    JSON.stringify({
      chapterId: chapter.chapterId,
      dryRun,
      failures,
      plainCount: job.plainQuestions.length,
      scenarioCount: job.scenarios.length,
      generatedAt: new Date().toISOString(),
    }, null, 2) + '\n'
  );
  return { chapterId: chapter.chapterId, failures: dryRun ? [] : failures, dryRun };
}

export async function main() {
  const args = resolveArgs(process.argv);
  console.log(`[stage-5] generation (provider=${config.aiProvider}${args.dryRun ? ', DRY-RUN' : ''})`);

  const catalog = loadCatalog();
  const chapters = args.chapter ? catalog.chapters.filter((c) => c.chapterId === args.chapter) : catalog.chapters;
  if (chapters.length === 0) fail('generate', `chapter ${args.chapter} not found in official catalog`);

  const mappingPath = path.join(config.stateDir, 'mapping.json');
  const mappingReport = fs.existsSync(mappingPath) ? JSON.parse(fs.readFileSync(mappingPath, 'utf8')) : null;
  const mappingByChapter = new Map((mappingReport?.chapters || []).map((m) => [m.chapterId, m]));
  if (!mappingReport) {
    fail('generate', 'mapping.json missing — run stages 1-4 first (source mapping is mandatory)');
  }

  let generated = 0;
  for (const chapter of chapters) {
    const mapping = mappingByChapter.get(chapter.chapterId) || null;
    if (!mapping || mapping.blocked) {
      console.warn(`[stage-5] SKIP ${chapter.chapterId} — chapter is BLOCKED (no module source mapping). Fail closed.`);
      continue;
    }
    const result = await generateChapter(chapter, mapping, args);
    generated++;
    const failCount = result.failures.length;
    if (failCount > 0) {
      console.warn(`[stage-5] ${chapter.chapterId}: ${failCount} item(s) failed — rerun with --chapter=${chapter.chapterId} to resume.`);
      result.failures.forEach((f) => console.warn(`   - ${f.item}: ${f.error}`));
    }
  }

  console.log(`[stage-5] OK — processed ${generated} chapter(s)${args.dryRun ? ' (dry-run — no AI calls made)' : ''}`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-5] FAILED: ${err.message}`);
    process.exit(1);
  });
}
