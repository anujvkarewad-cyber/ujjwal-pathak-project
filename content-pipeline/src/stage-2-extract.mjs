// Stage 2 — PDF/DOCX/text extraction.
// Converts every cached Drive file into a plain-text artifact with provenance
// (kind, sha256, page/section markers). Failures mark the file EXTRACT_FAILED
// so downstream mapping can never silently use a partial source.

import fs from 'node:fs';
import path from 'node:path';
import pdfParse from 'pdf-parse';
import mammoth from 'mammoth';
import { config, ensureDir } from './lib/config.mjs';
import { isMain } from './lib/main.mjs';

const MANIFEST = path.join(config.cacheDir, 'manifest.json');

function sectionText(page, lines) {
  return lines.map((l) => `[p${page}] ${l}`).join('\n');
}

async function extractOne(entry, outDir) {
  const srcPath = path.resolve(config.root, entry.path);
  if (!fs.existsSync(srcPath)) {
    return { status: 'EXTRACT_FAILED', error: `missing cached file ${srcPath}` };
  }
  const ext = path.extname(srcPath).toLowerCase();
  let text = '';

  if (ext === '.pdf') {
    const buf = fs.readFileSync(srcPath);
    const parsed = await pdfParse(buf);
    // Reconstruct page markers from pdf-parse's per-page data.
    if (parsed.getTextContent && typeof parsed.getTextContent === 'function') {
      text = parsed.text;
    } else {
      text = parsed.text;
      const pageTexts = (parsed.text || '').split('\f');
      text = pageTexts.map((t, i) => `[p${i + 1}] ${t}`).join('\n');
    }
  } else if (ext === '.docx') {
    const res = await mammoth.extractRawText({ path: srcPath });
    text = res.value;
  } else if (ext === '.txt' || ext === '.md') {
    text = fs.readFileSync(srcPath, 'utf8');
  } else {
    return { status: 'EXTRACT_FAILED', error: `unsupported extension ${ext}` };
  }

  if (!text || !text.trim()) {
    return { status: 'EXTRACT_FAILED', error: 'no text extracted' };
  }

  const outFile = path.join(outDir, `${entry.id}.txt`);
  fs.writeFileSync(
    outFile,
    `# source=${entry.name}\n# kind=${entry.kind}\n# sha256=${entry.sha256}\n# driveId=${entry.id}\n\n${text}\n`
  );
  return { status: 'ok', outFile: path.relative(config.root, outFile), chars: text.length };
}

export async function main() {
  console.log('[stage-2] extraction');
  if (!fs.existsSync(MANIFEST)) {
    console.error('[stage-2] FAILED: no drive manifest — run stage-1 first');
    process.exit(1);
  }
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
  const outDir = ensureDir(path.join(config.stateDir, 'extracted'));

  const results = {};
  let ok = 0;
  let failed = 0;
  for (const entry of Object.values(manifest.files)) {
    const r = await extractOne(entry, outDir);
    results[entry.id] = { ...entry, extraction: r };
    r.status === 'ok' ? ok++ : failed++;
  }

  fs.writeFileSync(
    path.join(config.stateDir, 'extraction.json'),
    JSON.stringify(results, null, 2) + '\n'
  );
  console.log(`[stage-2] OK — ${ok} extracted, ${failed} failed`);
  if (failed > 0) {
    console.log('[stage-2] failed files (excluded from all downstream stages):');
    for (const [id, r] of Object.entries(results)) {
      if (r.extraction.status !== 'ok') console.log(`  - ${r.name}: ${r.extraction.error}`);
    }
  }
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-2] FAILED: ${err.message}`);
    process.exit(1);
  });
}
