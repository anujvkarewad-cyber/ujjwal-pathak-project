// Stage 6 — Schema validation (AJV) against the canonical content model.
// Items failing the schema are blocked from review; results are stamped into
// each item's `validation` field and summarized in the chapter report.

import Ajv from 'ajv';
import fs from 'node:fs';
import path from 'node:path';
import { config } from './lib/config.mjs';
import { questionSchema, scenarioSchema } from './lib/schemas.mjs';
import { loadJob, saveJob, listJobChapterIds, allQuestions } from './lib/jobs.mjs';
import { isMain } from './lib/main.mjs';

const ajv = new Ajv({ allErrors: true, strict: false });
const validateQuestion = ajv.compile(questionSchema);
const validateScenario = ajv.compile(scenarioSchema);

export function run(args) {
  const chapterIds = args.chapter ? [args.chapter] : listJobChapterIds();
  if (chapterIds.length === 0) {
    console.error('[stage-6] no chapter jobs found (state/jobs/*/chapter.json)');
    process.exit(1);
  }

  let totalErrors = 0;
  for (const chapterId of chapterIds) {
    const job = loadJob(chapterId);
    if (!job) {
      console.error(`[stage-6] missing job for ${chapterId} — skipping (blocked)`);
      totalErrors++;
      continue;
    }
    for (const q of allQuestions(job)) {
      const ok = validateQuestion(q);
      q.validation = q.validation || {};
      q.validation.errors = (q.validation.errors || []).concat(
        (validateQuestion.errors || []).map((e) => `${e.instancePath || '/'} ${e.message}`)
      );
      if (!ok) totalErrors += (validateQuestion.errors || []).length;
      q._schemaOk = ok;
    }
    for (const s of job.scenarios || []) {
      const ok = validateScenario(s);
      s.validation = s.validation || {};
      s.validation.errors = (s.validation.errors || []).concat(
        (validateScenario.errors || []).map((e) => `${e.instancePath || '/'} ${e.message}`)
      );
      if (!ok) totalErrors += (validateScenario.errors || []).length;
      s._schemaOk = ok;
    }
    saveJob(chapterId, job);
  }

  if (totalErrors > 0) {
    console.error(`[stage-6] FAILED — ${totalErrors} schema error(s). Items are marked and blocked from review.`);
    process.exit(1);
  }
  console.log(`[stage-6] OK — ${chapterIds.length} chapter(s) pass schema validation`);
}

if (isMain(import.meta.url)) {
  const chapterArg = process.argv.find((a) => a.startsWith('--chapter='));
  run({ chapter: chapterArg ? chapterArg.split('=')[1] : null });
}
