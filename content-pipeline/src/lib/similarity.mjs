// Duplicate & copy-detection engine.
// 1. Exact match: normalized-text hash of prompt+options (and of the passage).
// 2. Near-copy vs source corpus: shingle MinHash + Jaccard similarity against
//    ICAI/RTP/MTP/PYQ fragments (anti-plagiarism) and against the question bank
//    (anti-duplication).
// Thresholds come from config (SIMILARITY_FLAG / SIMILARITY_BLOCK).

import { sha256Hex } from './hashing.mjs';

const STOPWORDS = new Set(
  'a,an,the,and,or,but,of,in,on,at,to,for,with,by,is,are,was,were,be,been,being,as,it,its,that,this,these,those,his,her,their,which,who,whom,shall,will,may,can,not,no,per,under,over,between,among,from,into,during,about,against,than,then,after,before,while,if,else,so,such,also,each,any,all,both,few,more,most,other,some,only,own,same,too,very,just,do,does,did,has,have,had,having'
    .split(',')
);

export function normalizeText(text) {
  if (text == null) return '';
  return String(text)
    .toLowerCase()
    .replace(/[’‘]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9'%₹$€\s-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function tokenize(text) {
  const words = normalizeText(text).split(' ').filter(Boolean);
  return words.filter((w) => !STOPWORDS.has(w) && w.length > 1);
}

export function shingles(tokens, k = 4) {
  const out = [];
  for (let i = 0; i + k <= tokens.length; i++) out.push(tokens.slice(i, i + k).join(' '));
  return out;
}

// Simple multiplicative-hash MinHash signature.
export function minHashSignature(shinglesArr, numHashes = 128, seedBase = 42) {
  const sig = new Array(numHashes).fill(Number.POSITIVE_INFINITY);
  for (const sh of shinglesArr) {
    for (let i = 0; i < numHashes; i++) {
      // FNV-1a-like per-seed hash of the shingle
      let h = (0x811c9dc5 ^ (seedBase + i * 2654435761)) >>> 0;
      for (let j = 0; j < sh.length; j++) {
        h ^= sh.charCodeAt(j);
        h = Math.imul(h, 0x01000193) >>> 0;
      }
      if (h < sig[i]) sig[i] = h;
    }
  }
  return sig;
}

export function jaccard(sigA, sigB) {
  if (!sigA || !sigB || sigA.length !== sigB.length || sigA.length === 0) return 0;
  let same = 0;
  for (let i = 0; i < sigA.length; i++) if (sigA[i] === sigB[i]) same++;
  return same / sigA.length;
}

// Containment: fraction of A's shingles present in B. The right metric for
// anti-copy checks (a short question embedding a verbatim source sentence
// must score ~1 even though the source fragment is much longer).
export function containment(sigA, sigB) {
  if (!sigA || !sigB || sigA.length !== sigB.length || sigA.length === 0) return 0;
  let same = 0;
  for (let i = 0; i < sigA.length; i++) if (sigA[i] === sigB[i]) same++;
  return same / sigA.length;
}

// Exact-match key for a question: normalized prompt + sorted option texts + answer.
export function questionFingerprint(q) {
  const parts = [normalizeText(q.prompt)];
  const opts = (q.options || []).map((o) => normalizeText(o.text)).sort();
  parts.push(...opts);
  parts.push(normalizeText(q.correctOptionId || ''));
  return sha256Hex(parts.join('\u0001'));
}

export function scenarioFingerprint(s) {
  return sha256Hex(normalizeText(s.passage || ''));
}

export function buildSourceIndex(fragments) {
  // fragments: [{ id, text }]
  return fragments.map((f) => {
    const tokens = tokenize(f.text);
    return {
      id: f.id,
      tokens: tokens.length,
      shingleSet: new Set(shingles(tokens)),
    };
  });
}

export function buildBankIndex(questions) {
  return questions.map((q) => {
    const tokens = tokenize(`${q.prompt} ${(q.options || []).map((o) => o.text).join(' ')} ${q.explanation || ''}`);
    const sh = shingles(tokens);
    return {
      id: q.id,
      fingerprint: questionFingerprint(q),
      shingleSet: new Set(sh),
      shingleCount: Math.max(1, sh.length),
    };
  });
}

function exactContainment(setA, setB) {
  if (!setA.size) return 0;
  let same = 0;
  for (const s of setA) if (setB.has(s)) same++;
  return same / setA.size;
}

function exactJaccard(setA, setB) {
  if (!setA.size && !setB.size) return 0;
  let inter = 0;
  const smaller = setA.size <= setB.size ? setA : setB;
  const larger = smaller === setA ? setB : setA;
  for (const s of smaller) if (larger.has(s)) inter++;
  const union = setA.size + setB.size - inter;
  return union === 0 ? 0 : inter / union;
}

// Check a candidate question against indexes. Returns
// { results: [{ against, refId, exact, similarity, field }], maxSourceSimilarity, maxBankSimilarity, verdict }
export function checkQuestionSimilarity(q, { sourceIndex = [], bankIndex = [], flag = 0.75, block = 0.9 } = {}) {
  const fp = questionFingerprint(q);
  const results = [];

  // Anti-copy: containment is computed PER FIELD (prompt, each option,
  // explanation) so a verbatim field can never be diluted by original fields.
  const fields = [
    { name: 'prompt', text: q.prompt || '' },
    ...(q.options || []).map((o) => ({ name: `option.${o.id}`, text: o.text || '' })),
    { name: 'explanation', text: q.explanation || '' },
  ].map((f) => ({ ...f, shingleSet: new Set(shingles(tokenize(f.text))) }));

  for (const src of sourceIndex) {
    if (src.tokens < 40) continue; // skip tiny fragments (headers, captions)
    let best = 0;
    let bestField = '';
    for (const field of fields) {
      if (field.shingleSet.size < 3) continue; // ignore very short fields
      const similarity = exactContainment(field.shingleSet, src.shingleSet);
      if (similarity > best) {
        best = similarity;
        bestField = field.name;
      }
    }
    if (best >= flag) {
      results.push({ against: 'source', refId: src.id, exact: false, similarity: round4(best), field: bestField });
    }
  }

  // Anti-duplication: Jaccard over the whole question text (sizes comparable).
  const tokens = tokenize(`${q.prompt} ${(q.options || []).map((o) => o.text).join(' ')} ${q.explanation || ''}`);
  const shSet = new Set(shingles(tokens));
  for (const b of bankIndex) {
    if (b.id === q.id) continue;
    const exact = b.fingerprint === fp;
    const similarity = exactJaccard(shSet, b.shingleSet);
    if (exact || similarity >= flag) {
      results.push({ against: 'bank', refId: b.id, exact, similarity: round4(exact ? 1 : similarity) });
    }
  }

  const maxSourceSimilarity = Math.max(0, ...results.filter((r) => r.against === 'source').map((r) => r.similarity));
  const maxBankSimilarity = Math.max(0, ...results.filter((r) => r.against === 'bank').map((r) => r.similarity));
  let verdict = 'clean';
  if (maxSourceSimilarity >= block || maxBankSimilarity >= block) verdict = 'blocked';
  else if (maxSourceSimilarity >= flag || maxBankSimilarity >= flag) verdict = 'flagged';
  return { results, maxSourceSimilarity, maxBankSimilarity, verdict, fingerprint: fp };
}

export function checkScenarioSimilarity(scenario, { sourceIndex = [], bankIndex = [], flag = 0.75, block = 0.9 } = {}) {
  const fp = scenarioFingerprint(scenario);
  const shSet = new Set(shingles(tokenize(scenario.passage)));
  const results = [];
  for (const src of sourceIndex) {
    if (src.tokens < 40) continue;
    const similarity = exactContainment(shSet, src.shingleSet);
    if (similarity >= flag) results.push({ against: 'source', refId: src.id, exact: false, similarity: round4(similarity) });
  }
  const maxSourceSimilarity = Math.max(0, ...results.map((r) => r.similarity));
  let verdict = 'clean';
  if (maxSourceSimilarity >= block) verdict = 'blocked';
  else if (maxSourceSimilarity >= flag) verdict = 'flagged';
  return { results, maxSourceSimilarity, verdict, fingerprint: fp };
}

function round4(n) {
  return Math.round(n * 10000) / 10000;
}
