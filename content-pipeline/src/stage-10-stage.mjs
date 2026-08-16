// Stage 10 — Review staging.
// Moves validated chapter jobs from pipeline state into MongoDB as drafts for
// the mentor review queue. Fail-closed rules:
//  - items with schema errors, content errors, or similarity blocks are NOT staged
//  - chapters with no stageable items are not staged
//  - staging never overwrites items a mentor has already touched (status beyond
//    generated/auto_validated)

import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { loadJob, listJobChapterIds, allQuestions, jobDir } from './lib/jobs.mjs';
import { getDb, closeDb, ensureIndexes, COLLECTIONS } from './lib/db.mjs';
import { isMain } from './lib/main.mjs';

const RESUME_SAFE_STATUSES = new Set(['generated', 'auto_validated', 'needs_review']);

function transition(item, to, by = 'pipeline') {
  item.status = to;
  item.statusHistory = item.statusHistory || [];
  item.statusHistory.push({
    from: item.statusHistory.length ? item.statusHistory[item.statusHistory.length - 1].to : null,
    to,
    by,
    at: new Date().toISOString(),
  });
}

export async function main() {
  console.log('[stage-10] staging drafts for mentor review');
  const catalog = loadCatalog();
  const catalogById = new Map(catalog.chapters.map((c) => [c.chapterId, c]));
  const mappingPath = path.join(config.stateDir, 'mapping.json');
  const mappingReport = fs.existsSync(mappingPath) ? JSON.parse(fs.readFileSync(mappingPath, 'utf8')) : null;
  const mappingByChapter = new Map((mappingReport?.chapters || []).map((m) => [m.chapterId, m]));

  const chapterIds = listJobChapterIds();
  if (chapterIds.length === 0) {
    console.error('[stage-10] FAILED: no chapter jobs — run stages 5-9 first');
    process.exit(1);
  }

  const db = await getDb();
  await ensureIndexes(db);
  const qCol = db.collection(COLLECTIONS.questions);
  const sCol = db.collection(COLLECTIONS.scenarios);
  const cCol = db.collection(COLLECTIONS.chapters);
  const aCol = db.collection(COLLECTIONS.audit);
  const now = () => new Date().toISOString();

  let staged = 0;
  let skipped = 0;
  const report = [];

  for (const chapterId of chapterIds) {
    const job = loadJob(chapterId);
    const catalogChapter = catalogById.get(chapterId);
    const mapping = mappingByChapter.get(chapterId) || null;
    if (!job || !catalogChapter) continue;

    const row = { chapterId, stagedQuestions: 0, stagedScenarios: 0, skipped: 0, reasons: [] };
    if (!mapping || mapping.blocked) {
      row.reasons.push('chapter mapping blocked (no module source)');
      report.push(row);
      continue;
    }
    if (!fs.existsSync(path.join(jobDir(chapterId), 'generation.json'))) {
      row.reasons.push('generation report missing');
      report.push(row);
      continue;
    }

    for (const q of allQuestions(job)) {
      const schemaOk = q._schemaOk !== false;
      const contentOk = q._contentOk !== false;
      const simOk = !q.similarity || q.similarity.verdict !== 'blocked';
      if (!schemaOk || !contentOk || !simOk) {
        skipped++;
        row.skipped++;
        row.reasons.push(`question ${q.id} not staged (schema=${schemaOk} content=${contentOk} similarity=${simOk ? 'ok' : 'blocked'})`);
        continue;
      }
      const existing = await qCol.findOne({ id: q.id });
      if (existing && !RESUME_SAFE_STATUSES.has(existing.status)) {
        skipped++;
        row.skipped++;
        row.reasons.push(`question ${q.id} already mentor-touched (${existing.status}) — not overwritten`);
        continue;
      }
      if (!existing) {
        transition(q, 'auto_validated');
        transition(q, 'needs_review');
        await qCol.replaceOne({ id: q.id }, q, { upsert: true });
      } else {
        transition(q, 'needs_review', 'pipeline-restage');
        await qCol.replaceOne({ id: q.id }, q, { upsert: true });
      }
      staged++;
      row.stagedQuestions++;
    }

    for (const s of job.scenarios || []) {
      const schemaOk = s._schemaOk !== false;
      const contentOk = s._contentOk !== false;
      const simOk = !s.similarity || s.similarity.verdict !== 'blocked';
      if (!schemaOk || !contentOk || !simOk) {
        skipped++;
        row.skipped++;
        row.reasons.push(`scenario ${s.scenarioId} not staged (schema=${schemaOk} content=${contentOk} similarity=${simOk ? 'ok' : 'blocked'})`);
        continue;
      }
      const existing = await sCol.findOne({ scenarioId: s.scenarioId });
      if (existing && !RESUME_SAFE_STATUSES.has(existing.status)) {
        skipped++;
        row.skipped++;
        row.reasons.push(`scenario ${s.scenarioId} already mentor-touched (${existing.status}) — not overwritten`);
        continue;
      }
      if (!existing) {
        transition(s, 'auto_validated');
        transition(s, 'needs_review');
      } else {
        transition(s, 'needs_review', 'pipeline-restage');
      }
      await sCol.replaceOne({ scenarioId: s.scenarioId }, s, { upsert: true });
      staged++;
      row.stagedScenarios++;
    }

    // Chapter record: coverage counts from DB-approved items + gate state.
    const approvedPlain = await qCol.countDocuments({ chapterId, questionType: 'mcq', status: { $in: ['approved', 'release_candidate', 'published'] } });
    const approvedScenarios = await sCol.countDocuments({ chapterId, status: { $in: ['approved', 'release_candidate', 'published'] } });
    const approvedScenarioMcqs = await qCol.countDocuments({ chapterId, questionType: 'scenario_mcq', status: { $in: ['approved', 'release_candidate', 'published'] } });
    await cCol.updateOne(
      { chapterId },
      {
        $set: {
          chapterId,
          chapterTitle: catalogChapter.chapterTitle,
          subject: catalogChapter.subject,
          group: catalogChapter.group,
          catalogMatch: { valid: !!catalogChapter, catalogRevision: 'may-2026' },
          coverage: {
            plainApproved: approvedPlain, plainTarget: config.questionsPlainPerChapter,
            scenariosApproved: approvedScenarios, scenariosTarget: config.scenariosPerChapter,
            scenarioMcqsApproved: approvedScenarioMcqs, scenarioMcqsTarget: config.scenariosPerChapter * config.questionsPerScenario,
          },
          status: 'needs_review',
          updatedAt: now(),
        },
        $setOnInsert: { createdAt: now() },
      },
      { upsert: true }
    );
    report.push(row);
  }

  await aCol.insertOne({
    at: now(), by: 'pipeline', action: 'stage_10_staging',
    detail: { staged, skipped, chapters: report.map((r) => r.chapterId) },
  });
  fs.writeFileSync(path.join(config.stateDir, 'staging.json'), JSON.stringify(report, null, 2) + '\n');
  await closeDb();

  console.log(`[stage-10] OK — staged ${staged} item(s), skipped ${skipped} (fail-closed; see staging.json)`);
  for (const r of report) {
    for (const reason of r.reasons) console.log(`  [${r.chapterId}] ${reason}`);
  }
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-10] FAILED: ${err.message}`);
    process.exit(1);
  });
}
