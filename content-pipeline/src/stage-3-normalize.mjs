// Stage 3 — Source normalization + chapter segmentation.
// Strips repeated headers/footers/watermarks, unifies whitespace, and splits
// each extracted file into fragments anchored by catalog chapter titles and
// numbers. Fragments without a chapter anchor remain UNMAPPED and are never
// fed to the model.

import fs from 'node:fs';
import path from 'node:path';
import { config, ensureDir } from './lib/config.mjs';
import { isMain } from './lib/main.mjs';
import { loadCatalog } from './lib/catalog.mjs';
import { normalizeText } from './lib/similarity.mjs';

function repeatedLines(text) {
  const counts = new Map();
  const lines = text.split('\n');
  const significant = lines.map((l) => l.trim()).filter((l) => l.length > 3 && l.length < 80);
  const sample = significant.slice(0, 600);
  for (const l of sample) {
    counts.set(l, (counts.get(l) || 0) + 1);
  }
  return new Set([...counts.entries()].filter(([, c]) => c >= 4).map(([l]) => l));
}

function chapterAnchors(catalog) {
  // anchor text → chapterId. Uses chapter number + first meaningful title words.
  const anchors = [];
  for (const ch of catalog.chapters) {
    const titleNorm = normalizeText(ch.chapterTitle);
    const firstWords = titleNorm.split(' ').slice(0, 4).join(' ');
    anchors.push({
      chapterId: ch.chapterId,
      number: ch.chapterNumber,
      firstWords: firstWords.length >= 8 ? firstWords : titleNorm,
      titleNorm,
    });
  }
  return anchors;
}

function findAnchor(line, anchors) {
  const norm = normalizeText(line);
  if (!norm || norm.length < 6) return null;
  const hasChapterNum = /^chapter\s+\d+/i.test(norm) || /^ch(apter)?[-.]?\s*\d+/i.test(norm);
  const withDigits = norm.match(/^\D*(\d+)[\s.:-]+(.{4,})$/);
  for (const a of anchors) {
    if (norm.includes(a.titleNorm)) return a.chapterId;
  }
  if (hasChapterNum) {
    for (const a of anchors) {
      if (norm.includes(String(a.number)) && a.firstWords && norm.includes(a.firstWords.split(' ')[0])) {
        return a.chapterId;
      }
    }
  }
  if (withDigits) {
    for (const a of anchors) {
      if (Number(withDigits[1]) === a.number) return a.chapterId;
    }
  }
  return null;
}

function segment(fileText, anchors) {
  const noise = repeatedLines(fileText);
  const clean = fileText
    .split('\n')
    .map((l) => l.replace(/\u00ad/g, '').trim())
    .filter((l) => l.length > 0 && !noise.has(l))
    .join('\n');

  const lines = clean.split('\n');
  const fragments = [];
  let current = { chapterId: null, lines: [] };
  const flush = () => {
    if (current.lines.length > 0) {
      const text = current.lines.join('\n').replace(/\s+/g, ' ').trim();
      if (text.length >= 40) {
        fragments.push({
          chapterId: current.chapterId,
          text,
          length: text.length,
        });
      }
    }
    current = { chapterId: current.chapterId, lines: [] };
  };

  for (const line of lines) {
    const anchor = findAnchor(line, anchors);
    if (anchor) {
      flush();
      current.chapterId = anchor;
      current.lines.push(line);
    } else {
      current.lines.push(line);
    }
    if (current.lines.length >= 120) flush();
  }
  flush();
  return fragments;
}

export async function main() {
  console.log('[stage-3] normalization');
  const extractionPath = path.join(config.stateDir, 'extraction.json');
  if (!fs.existsSync(extractionPath)) {
    console.error('[stage-3] FAILED: no extraction.json — run stage-2 first');
    process.exit(1);
  }
  const extraction = JSON.parse(fs.readFileSync(extractionPath, 'utf8'));
  const catalog = loadCatalog();
  const anchors = chapterAnchors(catalog);

  const outDir = ensureDir(path.join(config.stateDir, 'fragments'));
  const index = [];
  let id = 0;
  let unmappedCount = 0;

  for (const entry of Object.values(extraction)) {
    if (!entry.extraction || entry.extraction.status !== 'ok') continue;
    const txtPath = path.resolve(config.root, entry.extraction.outFile);
    const text = fs.readFileSync(txtPath, 'utf8');
    const fragments = segment(text, anchors);
    for (const frag of fragments) {
      id += 1;
      const fragId = `frag_${String(id).padStart(6, '0')}`;
      const mapped = frag.chapterId != null;
      if (!mapped) unmappedCount++;
      index.push({
        id: fragId,
        chapterId: frag.chapterId,
        mapped,
        kind: entry.kind,
        driveId: entry.id,
        fileName: entry.name,
        sha256: entry.sha256,
        length: frag.length,
        text: frag.text,
      });
    }
  }

  fs.writeFileSync(
    path.join(config.stateDir, 'fragments.json'),
    JSON.stringify(index, null, 2) + '\n'
  );
  console.log(`[stage-3] OK — ${index.length} fragments (${unmappedCount} unmapped, never used)`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-3] FAILED: ${err.message}`);
    process.exit(1);
  });
}
