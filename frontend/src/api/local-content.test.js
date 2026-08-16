// Regression tests for the mock adapter. Importing this module executes all
// store-building code at module load — if that throws (as it did with a
// block-scope `questions` bug), these tests fail and the app crash is caught
// in CI before it reaches the browser.
import { mockAnalytics, mockContent } from './local-content';

test('mock module loads and the review queue returns 100 questions (2 chapters × 50)', async () => {
  const queue = await mockContent('/api/content/queue', { params: { limit: 500 } });
  expect(queue.total).toBe(100);
  expect(queue.items).toHaveLength(100);

  const plain = queue.items.filter((q) => q.questionType === 'mcq');
  const scenarioMcqs = queue.items.filter((q) => q.questionType === 'scenario_mcq');
  expect(plain).toHaveLength(60);
  expect(scenarioMcqs).toHaveLength(40);

  // every scenario MCQ must carry a linkage { scenarioId, seq 1-4, blockTotal 4 }
  const byScenario = {};
  for (const q of scenarioMcqs) {
    expect(q.scenario.blockTotal).toBe(4);
    expect(q.scenario.seq).toBeGreaterThanOrEqual(1);
    expect(q.scenario.seq).toBeLessThanOrEqual(4);
    byScenario[q.scenario.scenarioId] = byScenario[q.scenario.scenarioId] || [];
    byScenario[q.scenario.scenarioId].push(q.scenario.seq);
  }
  expect(Object.keys(byScenario)).toHaveLength(10); // 2 chapters × 5 scenarios
  for (const [sid, seqs] of Object.entries(byScenario)) {
    expect(seqs.sort()).toEqual([1, 2, 3, 4]); // each block has exactly seq 1..4
    const block = await mockContent(`/api/content/scenarios/${sid}`);
    expect(block.questionIds).toHaveLength(4);
    expect(block.questions).toHaveLength(4);
    expect(block.passage).toContain('DEMO case study');
  }
});

test('mock queue filters work', async () => {
  const byType = await mockContent('/api/content/queue', { params: { questionType: 'mcq', limit: 500 } });
  expect(byType.total).toBe(60);
  const byChapter = await mockContent('/api/content/queue', { params: { chapterId: 'ch-law-03', limit: 500 } });
  expect(byChapter.total).toBe(50);
  const approved = await mockContent('/api/content/queue', { params: { status: 'approved', limit: 500 } });
  expect(approved.total).toBe(50); // ch-law-03 is pre-approved in the demo
});

test('mock chapter gate and coverage reflect approval state', async () => {
  const chapters = await mockContent('/api/content/chapters');
  expect(chapters.items).toHaveLength(2);
  const gate = await mockContent('/api/content/chapters/ch-law-03/gate');
  expect(gate.publishable).toBe(true);
  expect(gate.coverage).toEqual({
    plainApproved: 30,
    plainTarget: 30,
    scenariosApproved: 5,
    scenariosTarget: 5,
    scenarioMcqsApproved: 20,
    scenarioMcqsTarget: 20,
  });
  const blockedGate = await mockContent('/api/content/chapters/ch-acc-01/gate');
  expect(blockedGate.publishable).toBe(false);
  expect(blockedGate.errors.length).toBeGreaterThan(0);
});

test('mock question decisions mutate status and audit', async () => {
  const qid = 'adp_q_ch-acc-01_01';
  const decided = await mockContent(`/api/content/questions/${qid}/decision`, {
    method: 'POST',
    body: { decision: 'approve', comment: 'demo approve' },
  });
  expect(decided.status).toBe('approved');
  const audit = await mockContent('/api/content/audit', { params: { entityId: qid } });
  expect(audit.items.some((a) => a.action === 'approve')).toBe(true);
});

test('mock analytics overview, heatmap and student detail work', async () => {
  const overview = await mockAnalytics('/api/analytics/overview');
  expect(overview.consentOnStudents).toBe(5); // S-1004 sharing off
  expect(overview.chaptersCovered).toBe(2);

  const heatmap = await mockAnalytics('/api/analytics/heatmap');
  expect(heatmap.students).toHaveLength(5);
  expect(heatmap.chapters).toHaveLength(2);
  expect(heatmap.cells).toHaveLength(10);

  const detail = await mockAnalytics('/api/analytics/students/S-1004');
  expect(detail.sharing).toBe(false);
  expect(detail.summaries).toHaveLength(0);
});
