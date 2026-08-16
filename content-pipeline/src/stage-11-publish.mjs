// Stage 11 — Publish (gated).
// A chapter is publishable ONLY when (§7.3):
//   1. 30 plain MCQs approved          2. 5 scenarios approved
//   3. all 20 scenario MCQs approved   4. no blocking validation errors
//   5. all required source refs present 6. official catalog mapping valid
//   7. attempt-specific-risk items mentor-confirmed
// Builds web + mobile chunk trees + the shared published manifest, then
// records the release. On ANY gate failure nothing is exposed.

import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir, fail } from './lib/config.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { canonicalChapter, contentHashOf, hashFile } from './lib/hashing.mjs';
import { getDb, closeDb, ensureIndexes, COLLECTIONS } from './lib/db.mjs';
import { isMain } from './lib/main.mjs';

const PUBLISHABLE = new Set(['approved', 'release_candidate']);

function resolveArgs(argv) {
  const args = { chapter: null, all: false, by: process.env.PUBLISHED_BY || 'pipeline' };
  for (const a of argv) {
    if (a.startsWith('--chapter=')) args.chapter = a.split('=')[1];
    if (a === '--all') args.all = true;
  }
  return args;
}

function dailyGuard() {
  if (!config.studentRepoPath) return null;
  const guard = {};
  const targets = [
    ['learningDataHash', 'learning-data.js'],
    ['dailyMcqBankHash', 'mobile/src/data/dailyMcqBank.ts'],
    ['mcqMetadataHash', 'mobile/src/data/mcqMetadata.ts'],
  ];
  for (const [key, rel] of targets) {
    const p = path.resolve(config.studentRepoPath, rel);
    if (fs.existsSync(p)) guard[key] = `sha256:${hashFile(p)}`;
  }
  return guard;
}

export async function main() {
  const args = resolveArgs(process.argv);
  console.log(`[stage-11] publish ${args.chapter || (args.all ? 'ALL' : '(no chapter selected)')}`);
  if (!args.chapter && !args.all) {
    fail('publish', 'pass --chapter=<chapterId> or --all');
  }

  const catalog = loadCatalog();
  const catalogById = new Map(catalog.chapters.map((c) => [c.chapterId, c]));
  const mappingPath = path.join(config.stateDir, 'mapping.json');
  const mappingReport = fs.existsSync(mappingPath) ? JSON.parse(fs.readFileSync(mappingPath, 'utf8')) : null;
  const mappingByChapter = new Map((mappingReport?.chapters || []).map((m) => [m.chapterId, m]));

  const db = await getDb();
  await ensureIndexes(db);
  const qCol = db.collection(COLLECTIONS.questions);
  const sCol = db.collection(COLLECTIONS.scenarios);
  const cCol = db.collection(COLLECTIONS.chapters);
  const rCol = db.collection(COLLECTIONS.releases);
  const aCol = db.collection(COLLECTIONS.audit);

  // Chapters to publish: requested ∩ exists in catalog
  let targetIds;
  if (args.all) {
    targetIds = catalog.chapters.map((c) => c.chapterId);
  } else {
    if (!catalogById.has(args.chapter)) fail('publish', `chapter ${args.chapter} is not in the official catalog`);
    targetIds = [args.chapter];
  }

  const gates = [];
  for (const chapterId of targetIds) {
    const gate = { chapterId, checks: {}, errors: [], warnings: [] };
    const catalogChapter = catalogById.get(chapterId);
    const mapping = mappingByChapter.get(chapterId) || null;

    // 6. catalog mapping valid
    if (!catalogChapter || !mapping || mapping.blocked) {
      gate.errors.push('official chapter mapping invalid or blocked');
    }

    const plainApproved = await qCol.countDocuments({ chapterId, questionType: 'mcq', status: { $in: PUBLISHABLE } });
    const scenarios = await sCol.find({ chapterId, status: { $in: PUBLISHABLE } }).toArray();
    const scenarioMcqIds = [...new Set(scenarios.flatMap((s) => s.questionIds || []))];
    const scenarioMcqsApproved = await qCol.countDocuments({ id: { $in: scenarioMcqIds }, status: { $in: PUBLISHABLE } });

    gate.checks.plain = { have: plainApproved, need: config.questionsPlainPerChapter };
    gate.checks.scenarios = { have: scenarios.length, need: config.scenariosPerChapter };
    gate.checks.scenarioMcqs = { have: scenarioMcqsApproved, need: config.scenariosPerChapter * config.questionsPerScenario };

    if (plainApproved !== config.questionsPlainPerChapter) gate.errors.push('30 plain MCQs not all approved');
    if (scenarios.length !== config.scenariosPerChapter) gate.errors.push('5 scenarios not all approved');
    if (scenarioMcqsApproved !== config.scenariosPerChapter * config.questionsPerScenario) gate.errors.push('all 20 scenario MCQs not approved');

    // 4/5. blocking errors & refs & attempt-risk on publishable items
    const publishableQuestions = await qCol.find({ chapterId, status: { $in: PUBLISHABLE } }).toArray();
    const publishableScenarios = scenarios;
    for (const q of publishableQuestions) {
      const errors = (q.validation?.errors || []).length;
      if (errors > 0) gate.errors.push(`${q.id}: has ${errors} blocking validation error(s)`);
      if (!Array.isArray(q.icaiSourceRefs) || q.icaiSourceRefs.length === 0) gate.errors.push(`${q.id}: missing ICAI module refs`);
      if (!Array.isArray(q.calibrationRefs) || q.calibrationRefs.length === 0) gate.errors.push(`${q.id}: missing calibration refs`);
      if (q.attemptSpecificRisk && !q.attemptSpecificRiskConfirmed) gate.errors.push(`${q.id}: attempt-specific risk not mentor-confirmed`);
      if ((q.validation?.warnings || []).length > 0 && !q.warningsAcknowledged) gate.warnings.push(`${q.id}: warnings not acknowledged`);
    }
    for (const s of publishableScenarios) {
      if (!Array.isArray(s.icaiSourceRefs) || s.icaiSourceRefs.length === 0) gate.errors.push(`${s.scenarioId}: missing ICAI module refs`);
      if (!Array.isArray(s.calibrationRefs) || s.calibrationRefs.length === 0) gate.errors.push(`${s.scenarioId}: missing calibration refs`);
      if (s.attemptSpecificRisk && !s.attemptSpecificRiskConfirmed) gate.errors.push(`${s.scenarioId}: attempt-specific risk not mentor-confirmed`);
    }

    const chapterDoc = await cCol.findOne({ chapterId });
    if (chapterDoc?.blockingErrors?.length) {
      for (const e of chapterDoc.blockingErrors) gate.errors.push(e);
    }
    gates.push(gate);
  }

  const failing = gates.filter((g) => g.errors.length > 0);
  if (failing.length > 0) {
    console.error('[stage-11] PUBLISH ABORTED — gate failures:');
    for (const g of failing) {
      for (const e of g.errors) console.error(`  [${g.chapterId}] ${e}`);
    }
    fail('publish', 'publish gate failed — nothing was exposed. Previous revision stays live.');
  }

  // ── Build bundles ────────────────────────────────────────────────────────
  const guard = dailyGuard();
  const latest = await rCol.find({}).sort({ revision: -1 }).limit(1).toArray();
  const nextRevision = (latest[0]?.revision || 0) + 1;

  const manifestChapters = [];
  // Keep previously published chapters in the manifest (unchanged files).
  if (latest[0]?.manifest) {
    for (const ch of latest[0].manifest.chapters) {
      if (!targetIds.includes(ch.chapterId)) manifestChapters.push(ch);
    }
  }

  for (const chapterId of targetIds) {
    const questions = await qCol.find({ chapterId, status: { $in: PUBLISHABLE } }).toArray();
    const scenarios = await sCol.find({ chapterId, status: { $in: PUBLISHABLE } }).toArray();
    const plain = questions.filter((q) => q.questionType === 'mcq');
    const scenarioQuestions = questions.filter((q) => q.questionType === 'scenario_mcq');

    // DRAFT LEAKAGE GUARD: only publishable-status items may enter a bundle;
    // superseded/rejected history rows do not block (they can never enter a bundle).
    const bundleQuestionIds = [...plain, ...scenarioQuestions].map((q) => q.id).sort();
    const dbNonPublishable = await qCol.countDocuments({ chapterId, status: { $nin: [...PUBLISHABLE, 'superseded', 'rejected'] } });
    if (dbNonPublishable > 0) {
      fail('publish', `${chapterId}: chapter has ${dbNonPublishable} non-publishable question(s) — refusing to build bundle`);
    }
    const dbNonPublishableScenarios = await sCol.countDocuments({ chapterId, status: { $nin: [...PUBLISHABLE, 'superseded', 'rejected'] } });
    if (dbNonPublishableScenarios > 0) {
      fail('publish', `${chapterId}: chapter has ${dbNonPublishableScenarios} non-publishable scenario(s) — refusing to build bundle`);
    }

    const chapterBundle = {
      chapterId,
      revision: nextRevision,
      catalogRevision: 'may-2026',
      plainQuestions: plain,
      scenarios: scenarios.map((s) => ({
        scenarioId: s.scenarioId,
        passage: s.passage,
        icaiSourceRefs: s.icaiSourceRefs,
        calibrationRefs: s.calibrationRefs,
        questionIds: s.questionIds,
        questions: scenarioQuestions.filter((q) => s.questionIds.includes(q.id)),
      })),
    };
    const contentHash = contentHashOf(canonicalChapter(chapterBundle));

    const webFile = `chunks/${chapterId}.r${nextRevision}.${contentHash.slice(7, 15)}.json`;
    const mobileFile = `chunks/m/${chapterId}.r${nextRevision}.${contentHash.slice(7, 15)}.json`;
    const webOut = path.join(config.distDir, 'web', webFile);
    const mobileOut = path.join(config.distDir, 'mobile', mobileFile);
    ensureDir(path.dirname(webOut));
    ensureDir(path.dirname(mobileOut));
    const webPayload = JSON.stringify(chapterBundle, null, 2);
    const mobilePayload = JSON.stringify(chapterBundle, null, 2); // same content, platform packaging later
    fs.writeFileSync(webOut, webPayload + '\n');
    fs.writeFileSync(mobileOut, mobilePayload + '\n');

    manifestChapters.push({
      chapterId,
      counts: {
        plain: plain.length,
        scenarios: scenarios.length,
        scenarioMcqs: scenarioQuestions.length,
        total: plain.length + scenarioQuestions.length,
      },
      questionIds: bundleQuestionIds,
      chunkWeb: webFile,
      chunkMobile: mobileFile,
      contentHash,
    });
  }

  const manifest = {
    schemaVersion: 1,
    revision: nextRevision,
    publishedAt: new Date().toISOString(),
    publishedBy: args.by,
    catalogRevision: 'may-2026',
    chapters: manifestChapters.sort((a, b) => a.chapterId.localeCompare(b.chapterId)),
    dailyMcqFrozen: guard || { note: 'student repo unavailable — verify stage will re-check' },
  };
  const manifestPath = path.join(config.distDir, 'published-manifest.json');
  const tmpPath = `${manifestPath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(manifest, null, 2) + '\n');
  fs.renameSync(tmpPath, manifestPath); // atomic swap — readers never see partial state

  await rCol.insertOne({
    revision: nextRevision,
    manifest,
    publishedAt: manifest.publishedAt,
    publishedBy: args.by,
    chapters: targetIds,
    gates,
  });
  // Promote items + chapter docs
  for (const chapterId of targetIds) {
    await qCol.updateMany({ chapterId, status: 'release_candidate' }, { $set: { status: 'published', publishedInRevision: nextRevision, publishedAt: manifest.publishedAt } });
    await sCol.updateMany({ chapterId, status: 'release_candidate' }, { $set: { status: 'published', publishedInRevision: nextRevision, publishedAt: manifest.publishedAt } });
    await cCol.updateOne({ chapterId }, { $set: { status: 'published', releaseCandidate: { revision: nextRevision, at: manifest.publishedAt, by: args.by } } });
  }
  await aCol.insertOne({
    at: manifest.publishedAt, by: args.by, action: 'publish',
    detail: { revision: nextRevision, chapters: targetIds },
  });
  await closeDb();

  console.log(`[stage-11] OK — release revision ${nextRevision} published (${targetIds.length} chapter(s))`);
  console.log(`[stage-11] manifest: ${manifestPath}`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-11] FAILED: ${err.message}`);
    process.exit(1);
  });
}
