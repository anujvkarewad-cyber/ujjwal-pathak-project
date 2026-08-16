// Official ICAI chapter catalog — the ONLY chapter authority.
// Loads either:
//   a) the committed JSON snapshot (config/chapters.json), or
//   b) the canonical TypeScript source in the student repo
//      (mobile/src/data/icaiChapterCatalog.ts) when STUDENT_REPO_PATH is set.
// Any mismatch with the expected chapter count FAILS CLOSED.

import fs from 'node:fs';
import path from 'node:path';
import { config, fail } from './config.mjs';

const EXPECTED_EXPORTS = ['officialMcqChapterCatalog', 'icaiChapterCatalog', 'chapterCatalog', 'ICAI_CHAPTER_CATALOG', 'chapters'];

/**
 * Extract a TypeScript array literal of object literals (quoted keys) from a
 * .ts data file. Tolerant of `as const`, trailing commas, comments and the
 * typical codegen style used by mobile data files.
 */
export function parseTsArrayLiteral(source, exportName = null) {
  const lines = source.split('\n');
  let start = -1;
  const candidates = exportName ? [exportName] : EXPECTED_EXPORTS;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(/\/\*.*?\*\//g, '').replace(/\/\/.*$/, '');
    if (!line.includes('=')) continue;
    for (const cand of candidates) {
      const m = line.match(new RegExp(`(?:export\\s+)?(?:const|let|var)\\s+${cand}\\s*(?::[^=]*)?=\\s*\\[`));
      if (m) {
        start = i;
        break;
      }
    }
    if (start !== -1) break;
  }
  if (start === -1) return null;

  // The literal starts at the first '[' AFTER the '=' on the declaration line
  // (the type annotation may itself contain '[]', e.g. `: ChapterGroup[] = [`).
  const declLine = lines[start];
  const eqIdx = declLine.lastIndexOf('=');
  if (eqIdx === -1) return null;
  const bracketIdx = declLine.indexOf('[', eqIdx);
  if (bracketIdx === -1) return null;
  const joined = declLine.slice(bracketIdx) + '\n' + lines.slice(start + 1).join('\n');
  const openIdx = 0;
  let depth = 0;
  let inStr = false;
  let quote = '';
  for (let i = openIdx; i < joined.length; i++) {
    const ch = joined[i];
    if (inStr) {
      if (ch === '\\') { i++; continue; }
      if (ch === quote) inStr = false;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') { inStr = true; quote = ch; continue; }
    if (ch === '[') depth++;
    else if (ch === ']') {
      depth--;
      if (depth === 0) {
        const literal = joined.slice(openIdx, i + 1);
        return evalTsJson(literal);
      }
    }
  }
  return null;
}

function evalTsJson(literal) {
  // Remove trailing commas before ] or } and strip `as const` / type annotations
  // after the closing bracket. Object keys are expected to be quoted strings.
  const cleaned = literal
    .replace(/,\s*([}\]])/g, '$1')
    .replace(/\s+as\s+const\s*$/i, '')
    .replace(/;\s*$/, '')
    .trim();
  // eslint-disable-next-line no-new-func
  return new Function(`"use strict"; return (${cleaned});`)();
}

// Group I = Papers 1-3, Group II = Papers 4-6 (CA Intermediate new scheme).
export function groupFromPaper(paper) {
  const m = String(paper || '').match(/paper\s*(\d+)/i);
  if (m) return Number(m[1]) <= 3 ? 'Group 1' : 'Group 2';
  return '';
}

export function normalizeChapterEntry(entry) {
  // Accepts the field names used by icaiChapterCatalog.ts; emits the canonical shape.
  const chapterId = String(entry.chapterId ?? entry.id ?? entry.code ?? '');
  const chapterNumber = Number(entry.chapterNumber ?? entry.chapterNo ?? entry.number ?? entry.chapter);
  if (!chapterId || !Number.isFinite(chapterNumber)) return null;
  const paper = String(entry.paper ?? entry.paperNo ?? '');
  return {
    chapterId,
    subject: String(entry.subject ?? entry.paperName ?? ''),
    paper,
    section: String(entry.section ?? entry.part ?? ''),
    module: String(entry.module ?? entry.moduleName ?? ''),
    chapterNumber,
    chapterTitle: String(entry.chapterTitle ?? entry.title ?? ''),
    group: String(entry.group ?? entry.groupName ?? groupFromPaper(paper)),
    learningPoints: Array.isArray(entry.learningPoints) ? entry.learningPoints.map(String) : [],
  };
}

/**
 * Expand the `chapterGroups` shape used by the student repo's
 * icaiChapterCatalog.ts: [{ idPrefix, subject, paper, section, part, module,
 * sourceUrl, chapters: [[number, title], ...] }] → canonical chapter entries
 * (identical to the file's own flatMap expansion).
 */
export function expandChapterGroups(groups) {
  const chapters = [];
  for (const group of groups) {
    for (const [chapterNumber, title] of group.chapters || []) {
      chapters.push({
        id: `${group.idPrefix}-${chapterNumber}`,
        subject: group.subject,
        paper: group.paper,
        section: group.section,
        part: group.part,
        module: group.module,
        chapterNumber,
        title,
        officialTitle: `Chapter ${chapterNumber}: ${title}`,
        sourceUrl: group.sourceUrl,
      });
    }
  }
  return chapters.map((chapter, catalogOrder) => ({ ...chapter, catalogOrder }));
}

export function loadCatalog({ failOnEmpty = true, snapshotPath = null, tsPath = null, expectedCount = config.expectedChapterCount } = {}) {
  let entries = null;
  let source = '';

  const tsCandidate = tsPath || (config.studentRepoPath
    ? path.resolve(config.studentRepoPath, 'mobile/src/data/icaiChapterCatalog.ts')
    : null);
  if (tsCandidate && fs.existsSync(tsCandidate)) {
    const srcText = fs.readFileSync(tsCandidate, 'utf8');
    let parsed = parseTsArrayLiteral(srcText);
    if (parsed && Array.isArray(parsed)) {
      entries = parsed;
    } else {
      // Real file builds the catalog from a chapterGroups literal —
      // expand it with the same logic the file itself uses.
      const groups = parseTsArrayLiteral(srcText, 'chapterGroups');
      if (groups && Array.isArray(groups)) {
        entries = expandChapterGroups(groups);
      }
    }
    if (entries) {
      source = tsCandidate;
    } else {
      fail('catalog', `Could not parse chapter array from ${tsCandidate}`);
    }
  }
  if (!entries) {
    const snapPath = snapshotPath || config.catalogSnapshotPath;
    if (fs.existsSync(snapPath)) {
      const snap = JSON.parse(fs.readFileSync(snapPath, 'utf8'));
      entries = Array.isArray(snap.chapters) ? snap.chapters : null;
      source = snapPath;
    }
  }
  if (!entries) {
    fail('catalog', 'No catalog found. Set STUDENT_REPO_PATH or provide config/chapters.json (stage-0).');
  }

  const chapters = entries.map(normalizeChapterEntry).filter(Boolean);
  if (failOnEmpty && chapters.length === 0) {
    fail('catalog', 'Catalog parsed but contains no valid chapters.');
  }
  if (expectedCount > 0 && chapters.length !== expectedCount) {
    fail('catalog', `Catalog has ${chapters.length} chapters but EXPECTED_CHAPTER_COUNT=${expectedCount}. Refusing to continue.`);
  }
  const ids = new Set(chapters.map((c) => c.chapterId));
  if (ids.size !== chapters.length) {
    fail('catalog', 'Catalog contains duplicate chapterIds.');
  }
  return { chapters, source, count: chapters.length };
}
