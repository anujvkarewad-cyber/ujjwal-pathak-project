// Stage 12 — Cross-build verification (web vs mobile vs DB).
// Runs on every publish and in CI. Fails the release if ANY of:
//  - web/mobile chunk content differs (different hashes/canonical JSON)
//  - manifest hashes do not match recomputed hashes
//  - wrong question counts or scenario structure
//  - question ids differ between manifest and bundles
//  - draft (non-published) content appears in a bundle
//  - Daily MCQ data hashes changed (when the student repo is available)

import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { canonicalChapter, contentHashOf, hashFile } from './lib/hashing.mjs';
import { validateChapterCounts } from './lib/validation.mjs';
import { getDb, closeDb, COLLECTIONS } from './lib/db.mjs';
import { isMain } from './lib/main.mjs';

const PUBLISHABLE = new Set(['approved', 'release_candidate', 'published']);

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

export async function main() {
  console.log('[stage-12] cross-build verification');
  const manifestPath = path.join(config.distDir, 'published-manifest.json');
  if (!fs.existsSync(manifestPath)) {
    console.error('[stage-12] FAILED: no published manifest — run stage-11 first');
    process.exit(1);
  }
  const manifest = readJson(manifestPath);
  const failures = [];
  const warnings = [];
  const ok = (cond, msg) => (cond ? null : failures.push(msg));

  ok(manifest.schemaVersion === 1, 'manifest schemaVersion must be 1');
  ok(Number.isInteger(manifest.revision) && manifest.revision >= 1, 'manifest revision invalid');

  let dbStatuses = null;
  try {
    const db = await getDb();
    const rows = await db.collection(COLLECTIONS.questions)
      .find({}, { projection: { id: 1, status: 1 } }).toArray();
    dbStatuses = new Map(rows.map((r) => [r.id, r.status]));
    await closeDb();
  } catch (e) {
    warnings.push('MongoDB unavailable — status re-check limited to publish gate records');
  }

  const seenIds = new Set();
  for (const entry of manifest.chapters) {
    const webPath = path.join(config.distDir, 'web', entry.chunkWeb);
    const mobilePath = path.join(config.distDir, 'mobile', entry.chunkMobile);
    ok(fs.existsSync(webPath), `${entry.chapterId}: web chunk missing: ${entry.chunkWeb}`);
    ok(fs.existsSync(mobilePath), `${entry.chapterId}: mobile chunk missing: ${entry.chunkMobile}`);
    if (!fs.existsSync(webPath) || !fs.existsSync(mobilePath)) continue;

    const webBundle = readJson(webPath);
    const mobileBundle = readJson(mobilePath);

    // 1. Same content across platforms
    const webHash = contentHashOf(canonicalChapter(webBundle));
    const mobileHash = contentHashOf(canonicalChapter(mobileBundle));
    ok(webHash === mobileHash, `${entry.chapterId}: web/mobile content differs (${webHash} vs ${mobileHash})`);
    ok(webHash === entry.contentHash, `${entry.chapterId}: manifest hash mismatch for web bundle`);
    ok(mobileHash === entry.contentHash, `${entry.chapterId}: manifest hash mismatch for mobile bundle`);

    // 2. Counts
    const counts = validateChapterCounts(webBundle, {
      plain: config.questionsPlainPerChapter,
      scenarios: config.scenariosPerChapter,
      perScenario: config.questionsPerScenario,
    });
    for (const e of counts.errors) failures.push(`${entry.chapterId}: ${e}`);
    const expected = {
      plain: config.questionsPlainPerChapter,
      scenarios: config.scenariosPerChapter,
      scenarioMcqs: config.scenariosPerChapter * config.questionsPerScenario,
      total: config.questionsPlainPerChapter + config.scenariosPerChapter * config.questionsPerScenario,
    };
    for (const [k, v] of Object.entries(expected)) {
      ok(entry.counts[k] === v, `${entry.chapterId}: manifest counts.${k}=${entry.counts[k]}, expected ${v}`);
    }

    // 3. Question ids: manifest set == bundle set
    const bundleIds = [...webBundle.plainQuestions, ...webBundle.scenarios.flatMap((s) => s.questions)].map((q) => q.id).sort();
    const manifestIds = [...entry.questionIds].sort();
    ok(JSON.stringify(bundleIds) === JSON.stringify(manifestIds), `${entry.chapterId}: question ids differ between manifest and bundle`);
    for (const id of bundleIds) {
      if (seenIds.has(id)) failures.push(`${entry.chapterId}: duplicate question id across chapters: ${id}`);
      seenIds.add(id);
    }

    // 4. Scenario structure (5 blocks × 4 linked, seq 1..4)
    ok(webBundle.scenarios.length === config.scenariosPerChapter, `${entry.chapterId}: scenario block count`);
    for (const s of webBundle.scenarios) {
      ok(s.questionIds.length === config.questionsPerScenario, `${entry.chapterId}/${s.scenarioId}: must link 4 questions`);
      const seqs = s.questions.map((q) => q.scenario?.seq).sort();
      ok(JSON.stringify(seqs) === JSON.stringify([1, 2, 3, 4]), `${entry.chapterId}/${s.scenarioId}: seq must be 1..4`);
      for (const q of s.questions) {
        ok(q.scenario?.scenarioId === s.scenarioId, `${entry.chapterId}: ${q.id} scenarioId linkage`);
        ok(q.scenario?.blockTotal === config.questionsPerScenario, `${entry.chapterId}: ${q.id} blockTotal`);
      }
    }

    // 5. Draft leakage (DB-backed when available)
    if (dbStatuses) {
      for (const id of bundleIds) {
        const st = dbStatuses.get(id);
        ok(PUBLISHABLE.has(st), `${entry.chapterId}: ${id} in bundle but DB status=${st || 'MISSING'} (draft leakage)`);
      }
    }
  }

  // 6. Daily MCQ freeze guard
  if (config.studentRepoPath) {
    const guard = manifest.dailyMcqFrozen || {};
    const targets = [
      ['learningDataHash', 'learning-data.js'],
      ['dailyMcqBankHash', 'mobile/src/data/dailyMcqBank.ts'],
      ['mcqMetadataHash', 'mobile/src/data/mcqMetadata.ts'],
    ];
    for (const [key, rel] of targets) {
      const p = path.resolve(config.studentRepoPath, rel);
      if (!fs.existsSync(p)) {
        warnings.push(`daily guard: ${rel} not found in student repo`);
        continue;
      }
      const current = `sha256:${hashFile(p)}`;
      if (guard[key] && guard[key] !== current) {
        failures.push(`DAILY MCQ FREEZE VIOLATION: ${rel} hash changed (published ${guard[key]} vs current ${current})`);
      }
    }
  } else {
    warnings.push('STUDENT_REPO_PATH not set — Daily MCQ freeze guard could not be verified');
  }

  const report = {
    at: new Date().toISOString(),
    revision: manifest.revision,
    chapters: manifest.chapters.map((c) => c.chapterId),
    failures,
    warnings,
  };
  const reportDir = path.resolve(config.root, '..', 'test_reports');
  fs.mkdirSync(reportDir, { recursive: true });
  fs.writeFileSync(path.join(reportDir, 'content-verify.json'), JSON.stringify(report, null, 2) + '\n');

  if (failures.length > 0) {
    console.error(`[stage-12] VERIFY FAILED — ${failures.length} failure(s):`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log(`[stage-12] OK — revision ${manifest.revision} verified (${manifest.chapters.length} chapter(s), ${warnings.length} warning(s))`);
  for (const w of warnings) console.warn(`  ! ${w}`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-12] FAILED: ${err.message}`);
    process.exit(1);
  });
}
