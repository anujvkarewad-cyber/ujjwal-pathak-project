// Stage 7 — Content validation invariants (§5.3 of the design).
// Validates options, single-correct-answer structure, references, scenario
// linkage, per-chapter counts, and attempt-specific risk flags.
// Errors block review/publish; warnings require mentor acknowledgement.

import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { loadJob, saveJob, listJobChapterIds, allQuestions } from './lib/jobs.mjs';
import { validateQuestionContent, validateScenarioContent, validateChapterCounts } from './lib/validation.mjs';
import { isMain } from './lib/main.mjs';

export function run(args) {
  const catalog = loadCatalog();
  const catalogById = new Map(catalog.chapters.map((c) => [c.chapterId, c]));
  const chapterIds = args.chapter ? [args.chapter] : listJobChapterIds();
  if (chapterIds.length === 0) {
    console.error('[stage-7] no chapter jobs found');
    process.exit(1);
  }

  let totalErrors = 0;
  let totalWarnings = 0;
  const report = [];

  for (const chapterId of chapterIds) {
    const job = loadJob(chapterId);
    const chapterEntry = { chapterId, questions: [], scenarios: [], counts: null, blocked: false };
    if (!job) {
      chapterEntry.blocked = true;
      chapterEntry.reasons = ['no chapter job'];
      report.push(chapterEntry);
      continue;
    }
    const catalogChapter = catalogById.get(chapterId) || null;
    if (!catalogChapter) {
      chapterEntry.blocked = true;
      chapterEntry.reasons = [`chapterId ${chapterId} not in official catalog`];
      report.push(chapterEntry);
      totalErrors++;
      continue;
    }

    for (const q of allQuestions(job)) {
      const { errors, warnings } = validateQuestionContent(q, { catalogChapter });
      q.validation = q.validation || {};
      q.validation.errors = [...new Set([...(q.validation.errors || []), ...errors])];
      q.validation.warnings = [...new Set([...(q.validation.warnings || []), ...warnings])];
      q._contentOk = errors.length === 0;
      totalErrors += errors.length;
      totalWarnings += warnings.length;
      chapterEntry.questions.push({ id: q.id, errors, warnings });
    }

    for (const s of job.scenarios || []) {
      // Expected linkage = question records that claim this scenarioId.
      const expectedQuestionIds = allQuestions(job)
        .filter((x) => x.scenario && x.scenario.scenarioId === s.scenarioId)
        .map((x) => x.id);
      const { errors, warnings } = validateScenarioContent(s, {
        chapterId,
        expectedQuestionIds: expectedQuestionIds.length === 4 ? expectedQuestionIds : null,
      });
      s.validation = s.validation || {};
      s.validation.errors = [...new Set([...(s.validation.errors || []), ...errors])];
      s.validation.warnings = [...new Set([...(s.validation.warnings || []), ...warnings])];
      s._contentOk = errors.length === 0;
      totalErrors += errors.length;
      totalWarnings += warnings.length;
      chapterEntry.scenarios.push({ scenarioId: s.scenarioId, errors, warnings });
    }

    const counts = validateChapterCounts(job, {
      plain: config.questionsPlainPerChapter,
      scenarios: config.scenariosPerChapter,
      perScenario: config.questionsPerScenario,
    });
    chapterEntry.counts = counts;
    totalErrors += counts.errors.length;
    totalWarnings += counts.warnings.length;
    chapterEntry.blocked = totalErrors > 0 || counts.errors.length > 0;
    report.push(chapterEntry);
    saveJob(chapterId, job);
  }

  fs.writeFileSync(
    path.join(config.stateDir, 'content-validation.json'),
    JSON.stringify(report, null, 2) + '\n'
  );
  if (totalErrors > 0) {
    console.error(`[stage-7] FAILED — ${totalErrors} error(s), ${totalWarnings} warning(s). Errors block review & publish.`);
    process.exit(1);
  }
  console.log(`[stage-7] OK — ${chapterIds.length} chapter(s), ${totalWarnings} warning(s) for mentor acknowledgement`);
}

if (isMain(import.meta.url)) {
  const chapterArg = process.argv.find((a) => a.startsWith('--chapter='));
  run({ chapter: chapterArg ? chapterArg.split('=')[1] : null });
}
