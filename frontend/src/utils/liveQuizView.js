/*
 * Live-quiz tab view model — pure, no React, no fetch.
 *
 * It exists so the numbers on screen are testable without a browser: `LiveQuiz.jsx` only maps over
 * what these functions return. Every field read here comes from /api/live-quiz-admin/pool and
 * /api/live-quiz-admin/preview, and both endpoints are computed from the same `_candidates` /
 * `pick_questions` the student paper uses — so "what this student would get" here is what the student
 * gets, not an approximation of it.
 */

export const APPROVED = ['approved', 'release_candidate', 'published'];

/** Pool table for the mentor: one row per subject, plus the totals the header shows. */
export function poolView(payload) {
  const rows = (payload?.subjects || []).map((s) => ({
    subject: s.subject,
    readable: s.readable || 0,
    needsReview: s.needsReview || 0,
    other: s.other || 0,
    chapters: s.chapterCount || 0,
    topChapters: (s.chapters || []).slice(0, 3).map((c) => `${c.label} (${c.readable})`),
    revisions: s.revisions || [],
    // A subject whose whole pool is under review cannot make a paper at all.
    blocked: (s.readable || 0) === 0,
  }));
  rows.sort((a, b) => b.readable - a.readable);
  return {
    rows,
    total: payload?.total ?? rows.reduce((n, r) => n + r.readable + r.needsReview + r.other, 0),
    readable: payload?.readable ?? rows.reduce((n, r) => n + r.readable, 0),
    needsReview: payload?.needsReview ?? rows.reduce((n, r) => n + r.needsReview, 0),
    truncated: Boolean(payload?.truncated),
    subjects: rows.length,
  };
}

/**
 * The question the tab exists to answer: which question goes to which student.
 * Two views over one preview response — per student (their paper) and per question (who gets it).
 */
export function selectionView(preview) {
  const papers = (preview?.papers || []).map((p) => ({
    studentId: p.studentId,
    count: p.count || 0,
    questions: (p.questions || []).map((q) => ({
      id: q.id,
      prompt: q.prompt || '',
      chapter: q.chapter || '',
      subject: q.subject || '',
      options: (q.options || []).length,
      short: (q.prompt || '').replace(/\s+/g, ' ').slice(0, 150),
    })),
  }));
  const byQuestion = (preview?.byQuestion || []).map((e) => ({
    id: e.id,
    studentCount: e.studentCount || (e.students || []).length,
    students: e.students || [],
    pinned: Boolean(e.pinned),
  }));
  const students = Math.max(papers.length, 1);
  const slots = papers.reduce((n, p) => n + p.count, 0);
  return {
    papers,
    byQuestion,
    perStudentCount: preview?.perStudentCount ?? 0,
    distinctQuestions: preview?.distinctQuestions ?? new Set(papers.flatMap((p) => p.questions.map((q) => q.id))).size,
    // overlap = how alike two papers are. With a per-student seed this is normally low; a value of
    // perStudentCount for every pair means the seed is not varying (e.g. everyone has the same id).
    maxSharedByAnyQuestion: byQuestion.length ? byQuestion[0].studentCount : 0,
    coverage: slots ? Math.round((byQuestion.length / slots) * 100) : 0,
    pool: preview?.pool || { subjectRows: 0, afterChapterFilter: 0 },
    warnings: preview?.warnings || [],
    // Two different severities, deliberately not merged: no paper can be built at all (409) versus
    // a paper that will build but ignores the requested chapters. The first blocks the test, the
    // second only makes it wider than the mentor meant.
    blockers: (preview?.warnings || []).some((w) => warningKind(w) === 'empty'),
    chapterMiss: (preview?.warnings || []).some((w) => warningKind(w) === 'fallback'),
  };
}

/** Which of the two failure modes the backend can report, shown differently on purpose. */
export function warningKind(text) {
  if (/409/.test(text)) return 'empty';                 // no selectable questions at all
  if (/matched nothing/.test(text)) return 'fallback';  // chapter filter silently did nothing
  if (/narrowed/.test(text)) return 'info';             // chapter filter worked
  return 'info';
}

/** Student roster → the ids the preview needs, uppercase and deduped like `student_tests.py` does. */
export function normaliseStudentIds(lines) {
  const seen = new Set();
  const out = [];
  (Array.isArray(lines) ? lines : String(lines || '').split(/[\s,;]+/)).forEach((raw) => {
    const sid = String(raw || '').trim().toUpperCase();
    if (sid && !seen.has(sid)) { seen.add(sid); out.push(sid); }
  });
  return out;
}
