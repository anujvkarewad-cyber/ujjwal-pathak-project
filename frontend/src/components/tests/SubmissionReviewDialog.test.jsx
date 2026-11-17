import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { fetchSubmissionReview } from '@/api/tests';
import SubmissionReviewDialog from './SubmissionReviewDialog';

jest.mock('@/api/tests', () => ({ fetchSubmissionReview: jest.fn() }));

global.IS_REACT_ACT_ENVIRONMENT = true;

const student = { studentId: 'UMP0001', studentName: 'Aarav Sharma' };
const testInfo = { testId: 'T-1', title: 'Audit practice', kind: 'mcq-test' };
let container;
let root;

beforeEach(() => {
  fetchSubmissionReview.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

const renderDialog = async (kind = 'mcq-test') => {
  await act(async () => {
    root.render(<SubmissionReviewDialog open onOpenChange={() => {}} student={student} test={{ ...testInfo, kind }} />);
    await Promise.resolve();
  });
};

test('shows each MCQ mistake beside the correct option and explanation', async () => {
  fetchSubmissionReview.mockResolvedValue({
    student,
    test: { ...testInfo, kind: 'mcq-test' },
    submission: { score: 0, total: 1, scorePct: 0, at: '2026-11-17T10:00:00Z' },
    reviewAvailable: true,
    mcqReview: [{
      id: 'Q1', prompt: 'Which option is right?', options: ['Wrong option', 'Right option'],
      selected: 0, answer: 1, correct: false, explanation: 'The second option is right.',
    }],
  });

  await renderDialog('mcq-test');

  expect(document.body.textContent).toContain('Which option is right?');
  expect(document.body.textContent).toContain('Wrong option');
  expect(document.body.textContent).toContain('Right option');
  expect(document.body.textContent).toContain('The second option is right.');
  expect(document.body.textContent).toContain('Incorrect');
});

test('shows the uploaded-work and answer-key tabs for paper submissions', async () => {
  fetchSubmissionReview.mockResolvedValue({
    student,
    test: {
      ...testInfo,
      kind: 'paper-test',
      questionPaperUrl: '',
      answerSheetUrl: '',
      answerSheetText: 'Q1: Independence in mind and appearance.',
      markingScheme: 'Two marks for each point.',
      instructions: '',
    },
    submission: { score: 7, total: 10, scorePct: 70, selfMarks: true, answerUrl: '' },
    mcqReview: [],
    reviewAvailable: false,
  });

  await renderDialog('paper-test');
  expect(document.body.textContent).toContain('No student answer file was attached');

  const answerTab = Array.from(document.body.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Answer key');
  await act(async () => answerTab.click());
  expect(document.body.textContent).toContain('Q1: Independence in mind and appearance.');

  const schemeTab = Array.from(document.body.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Marking scheme');
  await act(async () => schemeTab.click());
  expect(document.body.textContent).toContain('Two marks for each point.');
});

test('explains when older MCQ records have no saved question-level answers', async () => {
  fetchSubmissionReview.mockResolvedValue({
    student,
    test: { ...testInfo, kind: 'mcq-test' },
    submission: { score: 1, total: 2, scorePct: 50 },
    reviewAvailable: false,
    mcqReview: [],
  });

  await renderDialog('mcq-test');

  expect(document.body.textContent).toMatch(/no saved question-by-question review/i);
});
