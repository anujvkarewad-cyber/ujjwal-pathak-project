// End-to-end pipeline test: catalog → fragments → mapping → job → validate →
// duplicate/coverage → stage → mentor-approve → publish → verify, using the
// in-memory DB (MONGO_URL=memory:// + MEMORY_DB_FILE) and a synthetic catalog.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'pipeline-e2e-'));

process.env.PIPELINE_STATE_DIR = path.join(TMP, 'state');
process.env.PIPELINE_DIST_DIR = path.join(TMP, 'dist');
process.env.CATALOG_SNAPSHOT_PATH = path.join(TMP, 'chapters.json');
process.env.MONGO_URL = 'memory://';
process.env.MEMORY_DB_FILE = path.join(TMP, 'memdb.json');
process.env.DB_NAME = 'e2e';
process.env.EXPECTED_CHAPTER_COUNT = '2';
process.env.STUDENT_REPO_PATH = ''; // empty, so dotenv can't re-inject the repo's .env value

const { config } = await import('../src/lib/config.mjs');
const { saveJob } = await import('../src/lib/jobs.mjs');
const catalogMod = await import('../src/lib/catalog.mjs');
const stage0 = await import('../src/stage-0-catalog.mjs');
const stage3 = await import('../src/stage-3-normalize.mjs');
const stage4 = await import('../src/stage-4-map.mjs');
const stage6 = await import('../src/stage-6-validate-schema.mjs');
const stage7 = await import('../src/stage-7-validate-content.mjs');
const stage8 = await import('../src/stage-8-duplicates.mjs');
const stage9 = await import('../src/stage-9-coverage.mjs');
const stage10 = await import('../src/stage-10-stage.mjs');
const stage11 = await import('../src/stage-11-publish.mjs');
const stage12 = await import('../src/stage-12-verify.mjs');
const { getDb, closeDb, COLLECTIONS } = await import('../src/lib/db.mjs');

const CHAPTER = {
  chapterId: 'ch-acc-01',
  subject: 'Accounting',
  paper: 'Paper 1',
  section: 'Accounting Standards',
  module: 'Module 1',
  chapterNumber: 1,
  chapterTitle: 'Introduction to Accounting Standards',
  group: 'Group 1',
  learningPoints: ['accounting standards framework', 'applicability of standards'],
};

const CHAPTER2 = {
  chapterId: 'ch-acc-02',
  subject: 'Accounting',
  paper: 'Paper 1',
  section: 'Accounting Standards',
  module: 'Module 1',
  chapterNumber: 2,
  chapterTitle: 'Conceptual Framework for Financial Reporting',
  group: 'Group 1',
  learningPoints: ['qualitative characteristics'],
};

// ── Synthetic but schema-valid content builder (no AI needed) ─────────────
const fill = (n) => String(n).padStart(2, '0');

function makeQuestion(chapter, i, { scenario = null } = {}) {
  const n = fill(i);
  return {
    id: `adp_q_${chapter.chapterId}_${n}`,
    revision: 1,
    chapterId: chapter.chapterId,
    subject: chapter.subject,
    paper: chapter.paper,
    section: chapter.section,
    module: chapter.module,
    chapterNumber: chapter.chapterNumber,
    chapterTitle: chapter.chapterTitle,
    questionType: scenario ? 'scenario_mcq' : 'mcq',
    difficulty: ['easy', 'moderate', 'hard'][i % 3],
    conceptTags: ['accounting-standards-framework', 'applicability-of-standards'],
    prompt: scenario
      ? `Referring to the facts in the case, question ${n} asks which accounting standard applies to the situation described in point ${n}.`
      : `Question ${n}: For a listed entity preparing financial statements for year ending March ${2000 + i}, which accounting standard governs disclosure of accounting policies in point ${n}?`,
    options: [
      { id: 'A', text: `AS 1 applies in scenario ${n}` },
      { id: 'B', text: `AS 2 applies in scenario ${n}` },
      { id: 'C', text: `AS 3 applies in scenario ${n}` },
      { id: 'D', text: `No standard applies in scenario ${n}` },
    ],
    correctOptionId: 'A',
    explanation: `Explanation for question ${n}: AS 1 governs disclosure of accounting policies for point ${n}; the other options misapply AS 2, AS 3, or ignore the requirement.`,
    icaiSourceRefs: [{ source: 'module', module: 'Module 1', chapter: 1, section: `1.${i % 7 + 1}`, edition: 'May 2026' }],
    calibrationRefs: [{ source: 'MTP', attempt: 'May 2026', questionRef: `Q${i % 10 + 1}` }],
    generationMeta: { model: 'fixture', promptVersion: '1.0.0', generatedAt: new Date().toISOString(), sourceDocIds: ['drv-fixture'] },
    scenario,
    attemptSpecificRisk: false,
    status: 'generated',
    statusHistory: [{ from: null, to: 'generated', by: 'fixture', at: new Date().toISOString() }],
    validation: { errors: [], warnings: [] },
  };
}

function buildJob(chapter) {
  const plainQuestions = [];
  for (let i = 1; i <= 30; i++) plainQuestions.push(makeQuestion(chapter, i));
  const scenarios = [];
  for (let s = 1; s <= 5; s++) {
    const scenarioId = `adp_s_${chapter.chapterId}_${fill(s)}`;
    const questionIds = [];
    const questions = [];
    for (let k = 1; k <= 4; k++) {
      const seq = 30 + (s - 1) * 4 + k;
      const q = makeQuestion(chapter, seq, { scenario: { scenarioId, seq: k, blockTotal: 4 } });
      questionIds.push(q.id);
      questions.push(q);
    }
    scenarios.push({
      scenarioId,
      revision: 1,
      chapterId: chapter.chapterId,
      passage: `Case study ${s} for ${chapter.chapterTitle}: A manufacturing company incorporated in Pune with a March year-end prepares its first Ind AS financial statements. The management of the company seeks advice on disclosure of accounting policies, treatment of items discussed in points ${s}1 to ${s}4, and consistency of presentation.`,
      icaiSourceRefs: [{ source: 'module', module: 'Module 1', chapter: 1, section: `2.${s}`, edition: 'May 2026' }],
      calibrationRefs: [{ source: 'RTP', attempt: 'May 2026', questionRef: `Case ${s}` }],
      attemptSpecificRisk: false,
      questionIds,
      status: 'generated',
      statusHistory: [{ from: null, to: 'generated', by: 'fixture', at: new Date().toISOString() }],
      validation: { errors: [], warnings: [] },
      questions,
    });
  }
  return { chapterId: chapter.chapterId, plainQuestions, scenarios };
}

test('full pipeline: source → staged → approved → published → verified (fail-closed at every gate)', async () => {
  // 1. Catalog authority (stage 0)
  fs.writeFileSync(
    config.catalogSnapshotPath,
    JSON.stringify({ catalogRevision: 'e2e', chapterCount: 2, chapters: [CHAPTER, CHAPTER2] })
  );
  await stage0.main();
  const catalog = catalogMod.loadCatalog({ expectedCount: 2 });
  assert.equal(catalog.count, 2);

  // 2. Simulate extraction (stage 2 output) — one module file for ch-acc-01 only.
  const extractedText =
    'Chapter 1: Introduction to Accounting Standards. Accounting Standards are written policy documents issued by an expert accounting body covering the aspects of recognition, measurement, treatment, presentation and disclosure of accounting transactions in the financial statements. They bring uniformity, comparability and consistency in financial reporting across entities and periods. AS 1 deals with the disclosure of significant accounting policies followed in preparing and presenting financial statements. The standard requires that all significant accounting policies adopted should be disclosed at one place, and any change in accounting policy having a material effect should be disclosed along with its impact.'.repeat(4);
  const extractedFile = path.join(TMP, 'module1.txt');
  fs.writeFileSync(extractedFile, extractedText);
  fs.mkdirSync(config.stateDir, { recursive: true });
  fs.writeFileSync(
    path.join(config.stateDir, 'extraction.json'),
    JSON.stringify({
      drv1: {
        id: 'drv1', kind: 'modules', name: 'module1.pdf', sha256: 'x',
        extraction: { status: 'ok', outFile: extractedFile },
      },
    })
  );

  // 3–4. Normalize + map (stages 3, 4)
  await stage3.main();
  const fragments = JSON.parse(fs.readFileSync(path.join(config.stateDir, 'fragments.json'), 'utf8'));
  assert.ok(fragments.some((f) => f.mapped && f.chapterId === 'ch-acc-01'), 'ch-acc-01 fragment mapped');
  await stage4.main();
  const mapping = JSON.parse(fs.readFileSync(path.join(config.stateDir, 'mapping.json'), 'utf8'));
  const mappedCh = mapping.chapters.find((c) => c.chapterId === 'ch-acc-01');
  const blockedCh = mapping.chapters.find((c) => c.chapterId === 'ch-acc-02');
  assert.equal(mappedCh.blocked, false);
  assert.equal(blockedCh.blocked, true, 'chapter without module source must be BLOCKED (fail closed)');

  // 5. Build + validate the chapter job (stages 6–9)
  saveJob(CHAPTER.chapterId, buildJob(CHAPTER));
  fs.writeFileSync(path.join(config.stateDir, 'jobs', CHAPTER.chapterId, 'generation.json'), JSON.stringify({ dryRun: false }));
  stage6.run({ chapter: CHAPTER.chapterId });
  stage7.run({ chapter: CHAPTER.chapterId });
  await stage8.run({ chapter: CHAPTER.chapterId });
  stage9.run({ chapter: CHAPTER.chapterId });

  // 6. Stage into DB (stage 10)
  await stage10.main();
  const db = await getDb();
  const qCol = db.collection(COLLECTIONS.questions);
  const sCol = db.collection(COLLECTIONS.scenarios);
  assert.equal(await qCol.countDocuments({ chapterId: CHAPTER.chapterId }), 50);
  assert.equal(await sCol.countDocuments({ chapterId: CHAPTER.chapterId }), 5);
  const stagedQ = await qCol.findOne({ id: 'adp_q_ch-acc-01_01' });
  assert.equal(stagedQ.status, 'needs_review');

  // 7. Mentor approves everything
  await qCol.updateMany({ chapterId: CHAPTER.chapterId }, { $set: { status: 'approved', warningsAcknowledged: true } });
  await sCol.updateMany({ chapterId: CHAPTER.chapterId }, { $set: { status: 'approved', warningsAcknowledged: true } });

  // 8. Publish (stage 11) — gate must pass
  process.argv = ['node', 'stage-11', '--chapter=ch-acc-01'];
  await stage11.main();
  const manifest = JSON.parse(fs.readFileSync(path.join(config.distDir, 'published-manifest.json'), 'utf8'));
  assert.equal(manifest.revision, 1);
  const entry = manifest.chapters.find((c) => c.chapterId === 'ch-acc-01');
  assert.deepEqual(entry.counts, { plain: 30, scenarios: 5, scenarioMcqs: 20, total: 50 });
  assert.equal(entry.questionIds.length, 50);
  const releaseDoc = await db.collection(COLLECTIONS.releases).findOne({ revision: 1 });
  assert.ok(releaseDoc, 'release recorded');

  // 9. Verify (stage 12) — web vs mobile vs DB
  await stage12.main();

  await closeDb();
});

test('publish gate fails closed on a draft question (child process, shared memory DB)', () => {
  // Inject a draft into the chapter after publishing; publish must exit(1).
  const inject = `
    process.env.MONGO_URL='memory://';
    process.env.MEMORY_DB_FILE=${JSON.stringify(path.join(TMP, 'memdb.json'))};
    process.env.DB_NAME='e2e';
    const { getDb, closeDb, COLLECTIONS } = await import(${JSON.stringify(path.join(ROOT, 'src/lib/db.mjs'))});
    const db = await getDb();
    await db.collection(COLLECTIONS.questions).insertOne({
      id: 'adp_q_ch-acc-01_draft01', chapterId: 'ch-acc-01', questionType: 'mcq',
      status: 'needs_review', prompt: 'draft', options: [], correctOptionId: 'A', explanation: 'draft',
      icaiSourceRefs: [], calibrationRefs: [], validation: { errors: [], warnings: [] },
    });
    await closeDb();
  `;
  execFileSync(process.execPath, ['--input-type=module', '-e', inject], { cwd: ROOT });

  const env = {
    ...process.env,
    PIPELINE_STATE_DIR: path.join(TMP, 'state'),
    PIPELINE_DIST_DIR: path.join(TMP, 'dist'),
    CATALOG_SNAPSHOT_PATH: path.join(TMP, 'chapters.json'),
    MONGO_URL: 'memory://',
    MEMORY_DB_FILE: path.join(TMP, 'memdb.json'),
    DB_NAME: 'e2e',
    EXPECTED_CHAPTER_COUNT: '2',
  };
  env.STUDENT_REPO_PATH = ''; // dotenv would re-inject the repo .env value otherwise
  let failed = false;
  try {
    execFileSync(process.execPath, ['src/stage-11-publish.mjs', '--chapter=ch-acc-01'], { cwd: ROOT, env, stdio: 'pipe' });
  } catch (e) {
    failed = true;
    const output = `${e.stdout || ''}${e.stderr || ''}`;
    assert.match(output, /non-publishable question|gate failure|PUBLISH ABORTED/, output);
  }
  assert.ok(failed, 'publish with a draft in the chapter MUST fail (draft leakage guard)');
});
