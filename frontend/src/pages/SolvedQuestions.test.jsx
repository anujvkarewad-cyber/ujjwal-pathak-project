import React, { act } from 'react';
import { createRoot } from 'react-dom/client';

jest.mock(
  'react-router-dom',
  () => ({
    Link: ({ to, children, ...props }) =>
      require('react').createElement('a', { href: to, ...props }, children),
  }),
  { virtual: true },
);

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

jest.mock('@/components/students/StudentAccessToggle', () => () =>
  require('react').createElement('span', { 'data-testid': 'mock-access-toggle' }, 'Access ON'),
);

const mockMutateAsync = jest.fn().mockResolvedValue({ remindedCount: 1 });

jest.mock('@/api/hooks', () => ({
  useSolvedQuestionsReport: jest.fn(),
  useRemindSolvedQuestions: () => ({
    isPending: false,
    mutateAsync: mockMutateAsync,
  }),
  useSendFeedback: () => ({
    isPending: false,
    mutateAsync: jest.fn().mockResolvedValue({ ok: true }),
  }),
}));

import { useSolvedQuestionsReport } from '@/api/hooks';
import SolvedQuestions from './SolvedQuestions';

global.IS_REACT_ACT_ENVIRONMENT = true;

test('renders separate DT and GST cards, submitted vs not-submitted rows, Drive proof links, and reminder flow', async () => {
  useSolvedQuestionsReport.mockReturnValue({
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: jest.fn(),
    data: {
      batches: ['All Batches', 'Last 25 days planner batch'],
      summary: {
        expectedCount: 2,
        submittedCount: 1,
        submittedSolvedCount: 1,
        loggedOnlyCount: 0,
        notSubmittedCount: 1,
        excusedCount: 0,
        submissionRate: 50,
        totalQuestionsSolved: 22,
        totalSheetsUploaded: 2,
      },
      subjectTotals: [
        { subject: 'Accounts', group: 'group1', questionsSolved: 0, studentsSubmitted: 0 },
        { subject: 'Law', group: 'group1', questionsSolved: 0, studentsSubmitted: 0 },
        { subject: 'DT', group: 'group1', questionsSolved: 14, studentsSubmitted: 1 },
        { subject: 'GST', group: 'group1', questionsSolved: 8, studentsSubmitted: 1 },
        { subject: 'Costing', group: 'group2', questionsSolved: 0, studentsSubmitted: 0 },
        { subject: 'Audit', group: 'group2', questionsSolved: 0, studentsSubmitted: 0 },
        { subject: 'FM', group: 'group2', questionsSolved: 0, studentsSubmitted: 0 },
        { subject: 'SM', group: 'group2', questionsSolved: 0, studentsSubmitted: 0 },
      ],
      items: [
        {
          studentId: 'UMP1003',
          studentName: 'Charu Defaulter',
          batch: 'Last 25 days planner batch',
          group: 'Both Groups',
          accessEnabled: true,
          notExpected: false,
          status: 'not_submitted',
          hours: 0,
          totalSolved: 0,
          bySubject: { Accounts: 0, Law: 0, DT: 0, GST: 0, Costing: 0, Audit: 0, FM: 0, SM: 0 },
          sheets: [],
        },
        {
          studentId: 'UMP1001',
          studentName: 'Aarav Submitter',
          batch: 'Last 25 days planner batch',
          group: 'Group 1',
          accessEnabled: true,
          notExpected: false,
          status: 'submitted',
          hours: 5.5,
          totalSolved: 22,
          bySubject: { Accounts: 0, Law: 0, DT: 14, GST: 8, Costing: 0, Audit: 0, FM: 0, SM: 0 },
          sheets: [
            {
              date: '2026-11-28',
              subject: 'DT',
              sheetName: 'PGBP Sheet 2',
              proofUrl: '/api/proof-file?fileId=dtDriveFile123',
            },
          ],
        },
      ],
    },
  });

  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => {
      root.render(<SolvedQuestions />);
    });

    expect(host.querySelector('[data-testid="sq-subject-card-DT"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="sq-subject-card-GST"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="sq-row-UMP1001"]').textContent).toContain('DT:');
    expect(host.querySelector('[data-testid="sq-row-UMP1001"]').textContent).toContain('14');
    expect(host.querySelector('[data-testid="sq-row-UMP1001"]').textContent).toContain('GST:');
    expect(host.querySelector('[data-testid="sq-row-UMP1001"]').textContent).toContain('8');
    expect(host.querySelector('[data-testid="sq-row-UMP1003"]').textContent).toContain('Not Submitted');

    const sheetLink = host.querySelector('[data-testid="sq-row-UMP1001"] a[target="_blank"]');
    expect(sheetLink.getAttribute('href')).toBe('https://drive.google.com/file/d/dtDriveFile123/view');

    // Filter to Not Submitted only
    await act(async () => {
      host.querySelector('[data-testid="sq-kpi-not-submitted"]').click();
    });
    expect(host.querySelector('[data-testid="sq-row-UMP1003"]')).not.toBeNull();
    expect(host.querySelector('[data-testid="sq-row-UMP1001"]')).toBeNull();

    // Open bulk reminder modal and send
    await act(async () => {
      host.querySelector('[data-testid="sq-remind-defaulters"]').click();
    });
    const sendBtn = [...host.querySelectorAll('button')].find((b) =>
      b.textContent.includes('Send Reminder (1)'),
    );
    expect(sendBtn).not.toBeUndefined();
    await act(async () => {
      sendBtn.click();
    });
    expect(mockMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ studentIds: ['UMP1003'] }),
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
