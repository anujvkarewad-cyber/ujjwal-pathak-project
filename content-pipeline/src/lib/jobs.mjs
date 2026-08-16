// Chapter job IO — each chapter's work products live under state/jobs/<chapterId>/.
// chapter.json shape: { chapterId, plainQuestions[], scenarios[{scenarioId, passage, refs, questionIds, questions[]}] }

import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir } from './config.mjs';

export function jobDir(chapterId) {
  return ensureDir(path.join(config.stateDir, 'jobs', chapterId));
}

export function jobFile(chapterId) {
  return path.join(jobDir(chapterId), 'chapter.json');
}

export function loadJob(chapterId) {
  const f = jobFile(chapterId);
  if (!fs.existsSync(f)) return null;
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

export function saveJob(chapterId, job) {
  const f = jobFile(chapterId);
  fs.writeFileSync(f, JSON.stringify(job, null, 2) + '\n');
  return f;
}

export function allQuestions(job) {
  return [
    ...(job.plainQuestions || []),
    ...(job.scenarios || []).flatMap((s) => s.questions || []),
  ];
}

export function listJobChapterIds() {
  const jobsRoot = path.join(config.stateDir, 'jobs');
  if (!fs.existsSync(jobsRoot)) return [];
  return fs.readdirSync(jobsRoot).filter((d) => fs.existsSync(path.join(jobsRoot, d, 'chapter.json')));
}

export function generationReport(job) {
  const plain = (job.plainQuestions || []).filter((q) => q.questionType === 'mcq').length;
  const scenarios = (job.scenarios || []).length;
  const scenarioMcqs = allQuestions(job).filter((q) => q.questionType === 'scenario_mcq').length;
  return { plain, scenarios, scenarioMcqs, total: plain + scenarioMcqs };
}
