// Mock adapter for the NEW AI Content + Analytics APIs (used when
// REACT_APP_MENTOR_API_URL is empty) — mirrors the existing mock pattern.
// Data is SYNTHETIC DEMO content only (no real ICAI material).

const now = new Date().toISOString();

const makeQ = (chapter, i, type = 'mcq', scenario = null) => {
  const n = `${i}`.padStart(2, '0');
  return {
    id: `adp_q_${chapter.chapterId}_${n}`,
    revision: 1,
    chapterId: chapter.chapterId,
    subject: chapter.subject,
    paper: chapter.paper,
    section: chapter.section,
    module: chapter.module,
    chapterNumber: chapter.chapterNumber,
    chapterTitle: chapter.chapterTitle,
    questionType: type,
    difficulty: ['easy', 'moderate', 'hard'][i % 3],
    conceptTags: ['demo-concept-a', 'demo-concept-b'],
    prompt: `DEMO question ${n} for ${chapter.chapterTitle}: which of the following statements is correct?`,
    options: [
      { id: 'A', text: `Statement A is correct for demo ${n}` },
      { id: 'B', text: `Statement B is correct for demo ${n}` },
      { id: 'C', text: `Statement C is correct for demo ${n}` },
      { id: 'D', text: `Statement D is correct for demo ${n}` },
    ],
    correctOptionId: 'A',
    explanation: `DEMO explanation for question ${n}: option A reflects the correct treatment under the standard.`,
    icaiSourceRefs: [{ source: 'module', module: chapter.module, chapter: chapter.chapterNumber, section: `1.${(i % 7) + 1}`, edition: 'May 2026' }],
    calibrationRefs: [{ source: 'MTP', attempt: 'May 2026', questionRef: `Q${(i % 10) + 1}`, calibrationNote: 'DEMO calibration benchmark' }],
    generationMeta: { model: 'demo', promptVersion: '1.0.0', generatedAt: now },
    scenario,
    attemptSpecificRisk: false,
    status: 'needs_review',
    statusHistory: [{ from: 'generated', to: 'needs_review', by: 'demo', at: now }],
    validation: { errors: [], warnings: [] },
    similarity: { verdict: 'clean', maxSourceSimilarity: 0.12, maxBankSimilarity: 0.08 },
    approval: null,
  };
};

const CHAPTERS = [
  { chapterId: 'ch-acc-01', subject: 'Accounting', paper: 'Paper 1', section: 'Accounting Standards', module: 'Module 1', chapterNumber: 1, chapterTitle: 'Introduction to Accounting Standards', group: 'Group 1' },
  { chapterId: 'ch-law-03', subject: 'Law', paper: 'Paper 2', section: 'Business Laws', module: 'Module 2', chapterNumber: 3, chapterTitle: 'Companies Act, 2013 — Incorporation', group: 'Group 1' },
];

function buildChapter(chapter, status) {
  const plain = [];
  for (let i = 1; i <= 30; i++) plain.push(makeQ(chapter, i));
  const scenarios = [];
  const scenarioQuestions = [];
  for (let s = 1; s <= 5; s++) {
    const scenarioId = `adp_s_${chapter.chapterId}_${`${s}`.padStart(2, '0')}`;
    const blockQuestions = [];
    const questionIds = [];
    for (let k = 1; k <= 4; k++) {
      const seq = 31 + (s - 1) * 4 + k;
      const q = makeQ(chapter, seq, 'scenario_mcq', { scenarioId, seq: k, blockTotal: 4 });
      blockQuestions.push(q);
      questionIds.push(q.id);
    }
    scenarioQuestions.push(...blockQuestions);
    scenarios.push({
      scenarioId,
      revision: 1,
      chapterId: chapter.chapterId,
      passage: `DEMO case study ${s} for ${chapter.chapterTitle}. A hypothetical company faces a practical situation involving the concepts of this chapter. Facts are presented for practice only.`,
      icaiSourceRefs: [{ source: 'module', module: chapter.module, chapter: chapter.chapterNumber, section: `2.${s}`, edition: 'May 2026' }],
      calibrationRefs: [{ source: 'RTP', attempt: 'May 2026', questionRef: `Case ${s}`, calibrationNote: 'DEMO calibration benchmark' }],
      attemptSpecificRisk: false,
      questionIds,
      status,
      statusHistory: [{ from: 'generated', to: status, by: 'demo', at: now }],
      validation: { errors: [], warnings: [] },
      approval: null,
    });
  }
  const all = [...plain, ...scenarioQuestions];
  all.forEach((q) => {
    q.status = status;
    if (status === 'approved') q.approval = { mentorId: 'demo', at: now, comments: 'demo approval' };
  });
  return { chapter, plain, scenarios, questions: all };
}

const store = {
  chapters: [],
  questions: [],
  scenarios: [],
  releases: [
    {
      revision: 1,
      publishedAt: now,
      publishedBy: 'demo',
      chapters: [],
      manifest: { schemaVersion: 1, revision: 1, chapters: [] },
    },
  ],
  audit: [{ at: now, by: 'demo', action: 'seed', entityId: null, entityType: 'demo', detail: { note: 'demo data' } }],
  followups: [],
  consent: { 'S-1001': true, 'S-1002': true, 'S-1003': true, 'S-1004': false, 'S-1005': true, 'S-1006': true },
};

for (const ch of CHAPTERS) {
  const built = buildChapter(ch, ch.chapterId === 'ch-law-03' ? 'approved' : 'needs_review');
  store.questions.push(...built.questions);
  store.scenarios.push(...built.scenarios);
  store.chapters.push({
    chapterId: ch.chapterId,
    chapterTitle: ch.chapterTitle,
    subject: ch.subject,
    group: ch.group,
    catalogMatch: { valid: true, catalogRevision: 'may-2026' },
    status: ch.chapterId === 'ch-law-03' ? 'approved' : 'needs_review',
    coverage: {
      plainApproved: ch.chapterId === 'ch-law-03' ? 30 : 0, plainTarget: 30,
      scenariosApproved: ch.chapterId === 'ch-law-03' ? 5 : 0, scenariosTarget: 5,
      scenarioMcqsApproved: ch.chapterId === 'ch-law-03' ? 20 : 0, scenarioMcqsTarget: 20,
    },
  });
}

const BANDS = ['Not assessed', 'Weak', 'Medium', 'Strong', 'Mastered'];
store.students = ['S-1001', 'S-1002', 'S-1003', 'S-1004', 'S-1005', 'S-1006'].map((sid, idx) => {
  const sharing = Boolean(store.consent[sid]);
  return {
    studentId: sid,
    sharing,
    summaries: sharing
      ? CHAPTERS.map((ch, j) => ({
          studentId: sid,
          chapterId: ch.chapterId,
          subject: ch.subject,
          group: ch.group,
          masteryBand: BANDS[(idx + j) % BANDS.length],
          attemptCount: (idx + 1) * 12 + j,
          accuracyRange: ['0-49', '0-49', '50-69', '70-84', '85-100'][(idx + j) % BANDS.length],
          lastActivityDate: new Date(Date.now() - ((idx * 5) % 20) * 86400000).toISOString().slice(0, 10),
          weakConceptTags: (idx + j) % BANDS.length < 2 ? ['demo-concept-a'] : [],
        }))
      : [],
    trend: sharing
      ? CHAPTERS.map((ch) => ({
          studentId: sid,
          chapterId: ch.chapterId,
          weekStart: '2026-08-01',
          masteryBand: idx === 1 ? 'Mastered' : 'Weak',
          attemptCount: 8,
          accuracyRange: '50-69',
        }))
      : [],
  };
});

store.followups.push({
  followupId: 'demo-fu-1',
  studentId: 'S-1002',
  title: 'DEMO follow-up: review weak chapter',
  priority: 'medium',
  rule: 'weak_chapter',
  status: 'open',
  createdAt: now,
  createdBy: 'demo',
  notes: [],
});

const wait = (ms = 60) => new Promise((r) => setTimeout(r, ms));

export const mockContent = async (path, { method = 'GET', body = null, params = null } = {}) => {
  await wait();
  if (path.startsWith('/api/auth/login')) return { token: 'mock-token', email: body?.email, role: 'mentor' };

  if (path === '/api/content/stats') {
    return {
      total: store.questions.length,
      chapters: store.chapters.length,
      needsReview: store.questions.filter((q) => q.status === 'needs_review').length,
      approved: store.questions.filter((q) => ['approved', 'release_candidate', 'published'].includes(q.status)).length,
      rejected: store.questions.filter((q) => q.status === 'rejected').length,
      changesRequested: store.questions.filter((q) => q.status === 'changes_requested').length,
    };
  }

  if (path === '/api/content/queue') {
    let items = [...store.questions];
    if (params?.chapterId) items = items.filter((q) => q.chapterId === params.chapterId);
    if (params?.questionType) items = items.filter((q) => q.questionType === params.questionType);
    if (params?.difficulty) items = items.filter((q) => q.difficulty === params.difficulty);
    if (params?.status) items = items.filter((q) => q.status === params.status);
    if (params?.subject) items = items.filter((q) => q.subject === params.subject);
    if (params?.hasWarnings !== undefined) {
      const want = params.hasWarnings === true || params.hasWarnings === 'true';
      items = items.filter((q) => Boolean((q.validation?.warnings || []).length) === want);
    }
    const limit = Number(params?.limit || 100);
    const offset = Number(params?.offset || 0);
    return { total: items.length, limit, offset, items: items.slice(offset, offset + limit) };
  }

  const qMatch = path.match(/^\/api\/content\/questions\/([^/]+)$/);
  if (qMatch) {
    const q = store.questions.find((x) => x.id === qMatch[1]);
    if (!q) throw Object.assign(new Error('Question not found'), { status: 404 });
    if (method === 'PUT') {
      Object.assign(q, body);
      return q;
    }
    return q;
  }
  const qDecide = path.match(/^\/api\/content\/questions\/([^/]+)\/decision$/);
  if (qDecide) {
    const q = store.questions.find((x) => x.id === qDecide[1]);
    const next = { approve: 'approved', reject: 'rejected', request_changes: 'changes_requested' }[body?.decision];
    q.status = next;
    q.statusHistory.push({ from: q.statusHistory.at(-1)?.to, to: next, by: 'demo-mentor', at: new Date().toISOString() });
    if (next === 'approved') q.approval = { mentorId: 'demo-mentor', at: new Date().toISOString(), comments: body?.comment || '' };
    store.audit.push({ at: new Date().toISOString(), by: 'demo-mentor', action: body?.decision, entityId: q.id, entityType: 'question', detail: { comment: body?.comment || '' } });
    return q;
  }

  const sMatch = path.match(/^\/api\/content\/scenarios\/([^/]+)$/);
  if (sMatch) {
    const s = store.scenarios.find((x) => x.scenarioId === sMatch[1]);
    if (!s) throw Object.assign(new Error('Scenario not found'), { status: 404 });
    return { ...s, questions: s.questionIds.map((id) => store.questions.find((q) => q.id === id)) };
  }
  const sDecide = path.match(/^\/api\/content\/scenarios\/([^/]+)\/decision$/);
  if (sDecide) {
    const s = store.scenarios.find((x) => x.scenarioId === sDecide[1]);
    const next = body?.decision === 'approve' ? 'approved' : 'rejected';
    s.status = next;
    for (const qid of s.questionIds) {
      const q = store.questions.find((x) => x.id === qid);
      q.status = next;
    }
    store.audit.push({ at: new Date().toISOString(), by: 'demo-mentor', action: `${body?.decision}_block`, entityId: s.scenarioId, entityType: 'scenario', detail: {} });
    return s;
  }

  if (path === '/api/content/chapters') {
    let items = [...store.chapters];
    if (params?.subject) items = items.filter((c) => c.subject === params.subject);
    if (params?.group) items = items.filter((c) => c.group === params.group);
    if (params?.status) items = items.filter((c) => c.status === params.status);
    return { items };
  }
  const gateMatch = path.match(/^\/api\/content\/chapters\/([^/]+)\/gate$/);
  if (gateMatch) {
    const ch = store.chapters.find((c) => c.chapterId === gateMatch[1]);
    const questions = store.questions.filter((q) => q.chapterId === ch.chapterId && ['approved', 'release_candidate'].includes(q.status));
    const scenarios = store.scenarios.filter((s) => s.chapterId === ch.chapterId && ['approved', 'release_candidate'].includes(s.status));
    const errors = [];
    if (questions.filter((q) => q.questionType === 'mcq').length !== 30) errors.push('30 plain MCQs not all approved');
    if (scenarios.length !== 5) errors.push('5 scenarios not all approved');
    if (questions.filter((q) => q.questionType === 'scenario_mcq').length !== 20) errors.push('all 20 scenario MCQs not approved');
    return {
      chapterId: ch.chapterId,
      chapterTitle: ch.chapterTitle,
      chapterStatus: ch.status,
      publishable: errors.length === 0,
      errors,
      warnings: [],
      coverage: {
        plainApproved: questions.filter((q) => q.questionType === 'mcq').length, plainTarget: 30,
        scenariosApproved: scenarios.length, scenariosTarget: 5,
        scenarioMcqsApproved: questions.filter((q) => q.questionType === 'scenario_mcq').length, scenarioMcqsTarget: 20,
      },
    };
  }
  const chApprove = path.match(/^\/api\/content\/chapters\/([^/]+)\/approve$/);
  if (chApprove) {
    const ch = store.chapters.find((c) => c.chapterId === chApprove[1]);
    const gate = await mockContent(`/api/content/chapters/${ch.chapterId}/gate`);
    if (!gate.publishable) throw Object.assign(new Error(JSON.stringify(gate.errors)), { status: 422 });
    ch.status = 'release_candidate';
    for (const q of store.questions.filter((q) => q.chapterId === ch.chapterId)) {
      if (q.status === 'approved') q.status = 'release_candidate';
    }
    store.audit.push({ at: new Date().toISOString(), by: 'demo-mentor', action: 'approve_chapter', entityId: ch.chapterId, entityType: 'chapter', detail: {} });
    return { ok: true, chapterId: ch.chapterId, status: 'release_candidate', coverage: gate.coverage };
  }
  const chPublish = path.match(/^\/api\/content\/chapters\/([^/]+)\/publish$/);
  if (chPublish) {
    const ch = store.chapters.find((c) => c.chapterId === chPublish[1]);
    const gate = await mockContent(`/api/content/chapters/${ch.chapterId}/gate`);
    if (!gate.publishable) throw Object.assign(new Error(JSON.stringify(gate.errors)), { status: 422 });
    ch.status = 'published';
    for (const q of store.questions.filter((q) => q.chapterId === ch.chapterId)) {
      if (['approved', 'release_candidate'].includes(q.status)) q.status = 'published';
    }
    for (const s of store.scenarios.filter((s) => s.chapterId === ch.chapterId)) {
      if (['approved', 'release_candidate'].includes(s.status)) s.status = 'published';
    }
    const revision = (store.releases[0]?.revision || 0) + 1;
    store.releases.unshift({
      revision,
      publishedAt: new Date().toISOString(),
      publishedBy: 'demo-mentor',
      chapters: [ch.chapterId],
      manifest: { schemaVersion: 1, revision, chapters: [{ chapterId: ch.chapterId, counts: gate.coverage }] },
    });
    store.audit.push({ at: new Date().toISOString(), by: 'demo-mentor', action: 'publish', entityId: ch.chapterId, entityType: 'chapter', detail: { revision } });
    return { ok: true, chapterId: ch.chapterId, status: 'published', revision, coverage: gate.coverage, filesWritten: false };
  }

  if (path === '/api/content/releases') return { items: store.releases };
  const relMatch = path.match(/^\/api\/content\/releases\/(\d+)$/);
  if (relMatch) {
    const r = store.releases.find((x) => x.revision === Number(relMatch[1]));
    if (!r) throw Object.assign(new Error('Release not found'), { status: 404 });
    return r;
  }
  if (path === '/api/content/audit') {
    let items = [...store.audit];
    if (params?.entityId) items = items.filter((a) => a.entityId === params.entityId);
    if (params?.action) items = items.filter((a) => a.action === params.action);
    return { items };
  }
  const valMatch = path.match(/^\/api\/content\/validation\/([^/]+)$/);
  if (valMatch) {
    const q = store.questions.find((x) => x.id === valMatch[1]);
    return {
      id: q.id,
      status: q.status,
      validation: q.validation,
      similarity: q.similarity,
      icaiSourceRefs: q.icaiSourceRefs,
      calibrationRefs: q.calibrationRefs,
      statusHistory: q.statusHistory,
    };
  }
  throw Object.assign(new Error(`mock: unknown route ${path}`), { status: 404 });
};

export const mockAnalytics = async (path, { method = 'GET', body = null, params = null } = {}) => {
  await wait();
  if (path === '/api/analytics/overview') {
    const consenting = store.students.filter((s) => s.sharing);
    const cells = consenting.flatMap((s) => s.summaries);
    const bandDistribution = { 'Not assessed': 0, Weak: 0, Medium: 0, Strong: 0, Mastered: 0 };
    for (const c of cells) bandDistribution[c.masteryBand] += 1;
    return {
      consentOnStudents: consenting.length,
      studentsWithSummaries: consenting.length,
      chaptersCovered: new Set(cells.map((c) => c.chapterId)).size,
      bandDistribution,
      inactiveChapterCells: 0,
      openFollowups: store.followups.filter((f) => ['open', 'in_progress'].includes(f.status)).length,
    };
  }
  if (path === '/api/analytics/students') {
    return {
      items: store.students.map((s) => ({
        studentId: s.studentId,
        sharing: s.sharing,
        consentUpdatedAt: new Date().toISOString(),
        summaryCount: s.sharing ? s.summaries.length : 0,
      })),
    };
  }
  const stuMatch = path.match(/^\/api\/analytics\/students\/([^/]+)$/);
  if (stuMatch) {
    const s = store.students.find((x) => x.studentId === stuMatch[1]) || { studentId: stuMatch[1], sharing: false, summaries: [], trend: [] };
    const summaries = s.sharing ? s.summaries : [];
    const weak = summaries.filter((x) => ['Weak', 'Not assessed'].includes(x.masteryBand));
    return {
      studentId: s.studentId,
      sharing: s.sharing,
      summaries,
      weakChapters: weak,
      weakConcepts: [...new Set(weak.flatMap((w) => w.weakConceptTags))],
      subjectPerformance: {},
      improvingChapters: s.studentId === 'S-1001' ? ['ch-acc-01'] : [],
      decliningChapters: s.studentId === 'S-1002' ? ['ch-law-03'] : [],
      lastActivity: summaries.map((x) => x.lastActivityDate).sort().at(-1) || null,
      recommendations: weak.length ? [`Focus practice on ${weak.length} weak chapter(s)`] : ['On track'],
      followups: store.followups.filter((f) => f.studentId === s.studentId),
    };
  }
  if (path === '/api/analytics/heatmap') {
    const consenting = store.students.filter((s) => s.sharing);
    let cells = consenting.flatMap((s) => s.summaries.map((c) => ({ ...c, inactive: false })));
    if (params?.band) cells = cells.filter((c) => c.masteryBand === params.band);
    if (params?.chapterId) cells = cells.filter((c) => c.chapterId === params.chapterId);
    return {
      students: [...new Set(cells.map((c) => c.studentId))].sort(),
      chapters: [...new Set(cells.map((c) => c.chapterId))].sort(),
      cells,
    };
  }
  if (path === '/api/analytics/weak-chapters') {
    const consenting = store.students.filter((s) => s.sharing);
    const cells = consenting.flatMap((s) => s.summaries);
    const agg = {};
    for (const c of cells) {
      agg[c.chapterId] = agg[c.chapterId] || { chapterId: c.chapterId, weakStudents: 0, totalStudents: 0 };
      agg[c.chapterId].totalStudents += 1;
      if (['Weak', 'Not assessed'].includes(c.masteryBand)) agg[c.chapterId].weakStudents += 1;
    }
    return { items: Object.values(agg).sort((a, b) => b.weakStudents - a.weakStudents) };
  }
  if (path === '/api/analytics/groups') {
    const items = [{ group: 'Group 1', bandCounts: { Weak: 3, Medium: 3, Strong: 2, Mastered: 2, 'Not assessed': 0 } }];
    return { items };
  }
  if (path === '/api/analytics/at-risk') {
    return { items: [{ studentId: 'S-1002', decliningChapters: 1, chapters: ['ch-law-03'], reason: 'declining_trend' }] };
  }
  if (path === '/api/analytics/improvement') {
    return {
      items: [
        { studentId: 'S-1001', improvingChapters: ['ch-acc-01'], decliningChapters: [] },
        { studentId: 'S-1002', improvingChapters: [], decliningChapters: ['ch-law-03'] },
      ],
    };
  }
  if (path === '/api/analytics/inactive') {
    return { items: [{ studentId: 'S-1005', chapterId: 'ch-acc-01', lastActivityDate: '2026-07-28' }] };
  }
  if (path === '/api/analytics/followups' && method === 'POST') {
    const doc = { followupId: `fu-${Date.now()}`, studentId: body?.studentId || null, title: body?.title, priority: body?.priority || 'medium', rule: body?.rule || null, status: 'open', createdAt: new Date().toISOString(), createdBy: 'demo-mentor', notes: [] };
    store.followups.unshift(doc);
    return doc;
  }
  const fuMatch = path.match(/^\/api\/analytics\/followups\/([^/]+)$/);
  if (fuMatch) {
    const f = store.followups.find((x) => x.followupId === fuMatch[1]);
    if (body?.status) f.status = body.status;
    if (body?.note) f.notes = [...(f.notes || []), { note: body.note, at: new Date().toISOString(), by: 'demo-mentor' }];
    return { ok: true, followupId: f.followupId };
  }
  if (path === '/api/analytics/followups') {
    let items = [...store.followups];
    if (params?.studentId) items = items.filter((f) => f.studentId === params.studentId);
    if (params?.status) items = items.filter((f) => f.status === params.status);
    return { items };
  }
  const consentMatch = path.match(/^\/api\/consent\/([^/]+)$/);
  if (consentMatch) return { studentId: consentMatch[1], sharing: store.consent[consentMatch[1]] ?? null };
  throw Object.assign(new Error(`mock: unknown route ${path}`), { status: 404 });
};
