// Stage 0 — Catalog sync & authority check.
// Reads the official chapter catalog (icaiChapterCatalog.ts from the student
// repo when STUDENT_REPO_PATH is set, else the committed snapshot), normalizes
// it and writes config/chapters.json. Fails closed on count mismatch,
// duplicate ids, or unparsable source.

import fs from 'node:fs';
import { config, ensureDir, fail } from './lib/config.mjs';
import { loadCatalog, parseTsArrayLiteral, expandChapterGroups } from './lib/catalog.mjs';
import { isMain } from './lib/main.mjs';

export async function main() {
  console.log('[stage-0] catalog sync');

  let chapters = [];
  let sourceLabel = 'snapshot';
  let catalogRevision = 'unknown';

  if (config.studentRepoPath) {
    const tsPath = `${config.studentRepoPath}/mobile/src/data/icaiChapterCatalog.ts`;
    if (!fs.existsSync(tsPath)) {
      fail('catalog', `STUDENT_REPO_PATH set but ${tsPath} not found`);
    }
    const srcText = fs.readFileSync(tsPath, 'utf8');
    const parsed = parseTsArrayLiteral(srcText);
    if (parsed && Array.isArray(parsed) && parsed.length > 0) {
      chapters = parsed;
    } else {
      const groups = parseTsArrayLiteral(srcText, 'chapterGroups');
      if (!groups || !Array.isArray(groups) || groups.length === 0) {
        fail('catalog', `Could not parse chapter array from ${tsPath}`);
      }
      chapters = expandChapterGroups(groups);
    }
    sourceLabel = tsPath;
  } else {
    const snapPath = config.catalogSnapshotPath;
    if (!fs.existsSync(snapPath)) {
      fail('catalog', `No catalog source. Set STUDENT_REPO_PATH or create ${snapPath}`);
    }
    const snap = JSON.parse(fs.readFileSync(snapPath, 'utf8'));
    chapters = Array.isArray(snap.chapters) ? snap.chapters : [];
    sourceLabel = snapPath;
    catalogRevision = snap.catalogRevision || 'unknown';
  }

  const catalog = loadCatalog();
  ensureDir('config');
  fs.writeFileSync(
    config.catalogSnapshotPath,
    JSON.stringify({ catalogRevision, source: sourceLabel, chapterCount: catalog.count, chapters: catalog.chapters }, null, 2) + '\n'
  );

  console.log(`[stage-0] OK — ${catalog.count} chapters from ${sourceLabel}`);
  console.log(`[stage-0] snapshot written to ${config.catalogSnapshotPath}`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-0] FAILED: ${err.message}`);
    if (err.details) console.error(err.details);
    process.exit(1);
  });
}
