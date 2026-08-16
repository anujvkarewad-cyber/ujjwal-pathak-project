// Stage 4 — Map fragments to the official 94-chapter catalog (fail closed).
// Builds each chapter's source bundle (module + RTP + MTP + PYQ fragments).
// A chapter with no mapped MODULE fragments is BLOCKED — generation will not
// run for it and it can never reach the review queue. Unmapped fragments are
// reported to the mentor, never silently dropped.

import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir } from './lib/config.mjs';
import { isMain } from './lib/main.mjs';
import { loadCatalog } from './lib/catalog.mjs';

export async function main() {
  console.log('[stage-4] catalog mapping');
  const fragPath = path.join(config.stateDir, 'fragments.json');
  if (!fs.existsSync(fragPath)) {
    console.error('[stage-4] FAILED: no fragments.json — run stage-3 first');
    process.exit(1);
  }
  const fragments = JSON.parse(fs.readFileSync(fragPath, 'utf8'));
  const catalog = loadCatalog();

  const byChapter = new Map(catalog.chapters.map((c) => [c.chapterId, { chapter: c, modules: [], rtp: [], mtp: [], pyq: [] }]));
  const unmapped = [];
  let mappedFragments = 0;

  for (const frag of fragments) {
    if (!frag.mapped || !frag.chapterId) {
      unmapped.push({ id: frag.id, fileName: frag.fileName, kind: frag.kind, length: frag.length });
      continue;
    }
    const bucket = byChapter.get(frag.chapterId);
    if (!bucket) {
      // Fragment anchored to a chapter that is NOT in the official catalog.
      unmapped.push({ id: frag.id, fileName: frag.fileName, kind: frag.kind, length: frag.length, reason: `chapterId ${frag.chapterId} not in official catalog` });
      continue;
    }
    const kind = frag.kind;
    if (kind === 'modules' || kind === 'rtp' || kind === 'mtp' || kind === 'pyq') {
      bucket[kind].push(frag);
      mappedFragments++;
    } else {
      unmapped.push({ id: frag.id, fileName: frag.fileName, kind, length: frag.length, reason: 'unknown kind' });
    }
  }

  const report = { chapters: [], unmapped, blockedChapters: [] };
  for (const [chapterId, bucket] of byChapter) {
    const reasons = [];
    if (bucket.modules.length === 0) reasons.push('no mapped ICAI module fragments');
    if (bucket.rtp.length === 0) reasons.push('no RTP fragments (calibration only, warning)');
    if (bucket.mtp.length === 0) reasons.push('no MTP fragments (calibration only, warning)');
    if (bucket.pyq.length === 0) reasons.push('no PYQ fragments (calibration only, warning)');

    const blocked = bucket.modules.length === 0;
    report.chapters.push({
      chapterId,
      chapterTitle: bucket.chapter.chapterTitle,
      subject: bucket.chapter.subject,
      group: bucket.chapter.group,
      blocked,
      reasons,
      fragmentCounts: {
        modules: bucket.modules.length,
        rtp: bucket.rtp.length,
        mtp: bucket.mtp.length,
        pyq: bucket.pyq.length,
      },
      moduleFragmentIds: bucket.modules.map((f) => f.id),
      rtpFragmentIds: bucket.rtp.map((f) => f.id),
      mtpFragmentIds: bucket.mtp.map((f) => f.id),
      pyqFragmentIds: bucket.pyq.map((f) => f.id),
    });
    if (blocked) report.blockedChapters.push(chapterId);
  }

  const outDir = ensureDir(config.stateDir);
  fs.writeFileSync(path.join(outDir, 'mapping.json'), JSON.stringify(report, null, 2) + '\n');

  console.log(`[stage-4] mapped ${mappedFragments} fragments into ${report.chapters.length} chapters`);
  console.log(`[stage-4] ${report.blockedChapters.length} chapter(s) BLOCKED (no module source)`);
  if (report.blockedChapters.length > 0) {
    console.log(`  blocked: ${report.blockedChapters.join(', ')}`);
  }
  console.log(`[stage-4] ${unmapped.length} fragment(s) unmapped (never used; see mapping.json)`);
  if (report.blockedChapters.length === report.chapters.length) {
    console.error('[stage-4] FAILED: every chapter is blocked — check DRIVE_FOLDER_MODULES and catalog titles.');
    process.exit(1);
  }
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-4] FAILED: ${err.message}`);
    process.exit(1);
  });
}
