// Stage 9 — Concept coverage check.
// Every learningPoint in the official catalog entry must be covered by at
// least one question's conceptTags; over/under-represented tags are reported.
// Uncovered learning points become chapter warnings the mentor must ack
// before the chapter can be published.

import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { loadJob, saveJob, listJobChapterIds, allQuestions } from './lib/jobs.mjs';
import { isMain } from './lib/main.mjs';
import { normalizeText } from './lib/similarity.mjs';

function tagMatchesPoint(tags, point) {
  const p = normalizeText(point);
  for (const t of tags) {
    const tn = normalizeText(t);
    if (p.includes(tn) || tn.includes(p)) return true;
  }
  return false;
}

export function run(args) {
  console.log('[stage-9] concept coverage');
  const catalog = loadCatalog();
  const byId = new Map(catalog.chapters.map((c) => [c.chapterId, c]));
  const chapterIds = args.chapter ? [args.chapter] : listJobChapterIds();
  if (chapterIds.length === 0) {
    console.error('[stage-9] no chapter jobs found');
    process.exit(1);
  }

  const report = [];
  for (const chapterId of chapterIds) {
    const entry = byId.get(chapterId);
    const job = loadJob(chapterId);
    if (!entry || !job) continue;

    const questions = allQuestions(job);
    const tagCounts = new Map();
    for (const q of questions) {
      for (const t of q.conceptTags || []) {
        const key = normalizeText(t);
        tagCounts.set(key, (tagCounts.get(key) || 0) + 1);
      }
    }

    const uncovered = [];
    const points = entry.learningPoints || [];
    for (const point of points) {
      const covered = questions.some((q) => tagMatchesPoint(q.conceptTags || [], point));
      if (!covered) uncovered.push(point);
    }

    const over = [...tagCounts.entries()].filter(([, c]) => c > Math.max(3, Math.ceil(questions.length / 10))).map(([t, c]) => ({ tag: t, count: c }));
    const under = [...tagCounts.entries()].filter(([, c]) => c === 1 && questions.length > 20).map(([t, c]) => ({ tag: t, count: c }));

    const row = { chapterId, learningPoints: points.length, uncovered, overRepresented: over, underRepresented: under };
    if (uncovered.length > 0) {
      job.coverageWarnings = job.coverageWarnings || [];
      job.coverageWarnings = [...new Set([...job.coverageWarnings, ...uncovered.map((p) => `learning point uncovered: ${p}`)])];
      saveJob(chapterId, job);
    }
    report.push(row);
  }

  fs.writeFileSync(path.join(config.stateDir, 'coverage.json'), JSON.stringify(report, null, 2) + '\n');
  const uncoveredTotal = report.reduce((a, r) => a + r.uncovered.length, 0);
  console.log(`[stage-9] OK — ${report.length} chapter(s), ${uncoveredTotal} uncovered learning point(s)`);
}

if (isMain(import.meta.url)) {
  const chapterArg = process.argv.find((a) => a.startsWith('--chapter='));
  run({ chapter: chapterArg ? chapterArg.split('=')[1] : null });
}
