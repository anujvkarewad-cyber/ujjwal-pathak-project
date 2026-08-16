// Stage 8 — Duplicate & copy-detection gates.
// 1. Exact-match fingerprint of prompt+options (whole bank, incl. drafts).
// 2. MinHash/shingle similarity vs the chapter's ICAI/RTP/MTP/PYQ source
//    fragments (anti-plagiarism — the AI must not reproduce ICAI text).
// 3. MinHash similarity vs the existing question bank (anti-duplication).
// Items at/above SIMILARITY_BLOCK are auto-blocked from review.

import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { loadJob, saveJob, listJobChapterIds, allQuestions } from './lib/jobs.mjs';
import {
  buildSourceIndex, buildBankIndex, checkQuestionSimilarity, checkScenarioSimilarity,
} from './lib/similarity.mjs';
import { getDb, closeDb, COLLECTIONS } from './lib/db.mjs';
import { isMain } from './lib/main.mjs';

function loadBankIndexFromJobs(excludeChapterIds) {
  const questions = [];
  for (const cid of listJobChapterIds()) {
    if (excludeChapterIds.has(cid)) continue;
    const job = loadJob(cid);
    questions.push(...allQuestions(job || {}));
  }
  return buildBankIndex(questions);
}

async function loadBankIndexFromDb() {
  const db = await getDb();
  const rows = await db.collection(COLLECTIONS.questions)
    .find({}, { projection: { id: 1, prompt: 1, options: 1, correctOptionId: 1, explanation: 1 } })
    .toArray();
  return buildBankIndex(rows);
}

function sourceIndexFor(chapterId) {
  const fragPath = path.join(config.stateDir, 'fragments.json');
  if (!fs.existsSync(fragPath)) return [];
  const fragments = JSON.parse(fs.readFileSync(fragPath, 'utf8'));
  return buildSourceIndex(fragments.filter((f) => f.mapped && f.chapterId === chapterId));
}

export async function run(args) {
  console.log('[stage-8] duplicate & similarity checks');
  const chapterIds = args.chapter ? [args.chapter] : listJobChapterIds();
  if (chapterIds.length === 0) {
    console.error('[stage-8] no chapter jobs found');
    process.exit(1);
  }

  let bankIndex = loadBankIndexFromJobs(new Set(chapterIds));
  try {
    const dbBank = await loadBankIndexFromDb();
    bankIndex = [...bankIndex, ...dbBank];
  } catch (e) {
    console.warn('[stage-8] DB bank unavailable — checking against local jobs only');
  } finally {
    await closeDb().catch(() => {});
  }

  let blocked = 0;
  let flagged = 0;
  const summary = [];

  for (const chapterId of chapterIds) {
    const job = loadJob(chapterId);
    if (!job) continue;
    const sourceIndex = sourceIndexFor(chapterId);
    const chapterSummary = { chapterId, blocked: 0, flagged: 0, items: [] };

    for (const q of allQuestions(job)) {
      const check = checkQuestionSimilarity(q, {
        sourceIndex,
        bankIndex: bankIndex.filter((b) => b.id !== q.id),
        flag: config.similarityFlag,
        block: config.similarityBlock,
      });
      q.similarity = check;
      if (check.verdict === 'blocked') {
        blocked++;
        chapterSummary.blocked++;
      } else if (check.verdict === 'flagged') {
        flagged++;
        chapterSummary.flagged++;
      }
      chapterSummary.items.push({ id: q.id, verdict: check.verdict, maxSourceSimilarity: check.maxSourceSimilarity, maxBankSimilarity: check.maxBankSimilarity });
    }

    for (const s of job.scenarios || []) {
      const check = checkScenarioSimilarity(s, {
        sourceIndex,
        flag: config.similarityFlag,
        block: config.similarityBlock,
      });
      s.similarity = check;
      if (check.verdict === 'blocked') {
        blocked++;
        chapterSummary.blocked++;
      } else if (check.verdict === 'flagged') {
        flagged++;
        chapterSummary.flagged++;
      }
      chapterSummary.items.push({ id: s.scenarioId, verdict: check.verdict, maxSourceSimilarity: check.maxSourceSimilarity });
    }

    saveJob(chapterId, job);
    summary.push(chapterSummary);
  }

  fs.writeFileSync(path.join(config.stateDir, 'similarity.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(`[stage-8] OK — ${blocked} blocked, ${flagged} flagged (thresholds flag=${config.similarityFlag} block=${config.similarityBlock})`);
  if (blocked > 0) {
    console.error('[stage-8] blocked items cannot enter the review queue and are auto-rejected.');
    process.exit(1);
  }
}

if (isMain(import.meta.url)) {
  const chapterArg = process.argv.find((a) => a.startsWith('--chapter='));
  run({ chapter: chapterArg ? chapterArg.split('=')[1] : null });
}
