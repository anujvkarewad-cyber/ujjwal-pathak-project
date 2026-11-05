import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import TargetPlans from './TargetPlans';
import * as targetPlansApi from '@/api/targetPlans';
import * as dailyTargetsApi from '@/api/dailyTargets';

global.IS_REACT_ACT_ENVIRONMENT = true;

jest.mock('@/api/dailyTargets', () => ({
  fetchTargetOptions: jest.fn(),
  previewTargetAudience: jest.fn(),
}));

jest.mock('@/api/targetPlans', () => ({
  MAX_START_DAY: 40,
  fetchTargetPlans: jest.fn(),
  publishTargetPlan: jest.fn(),
  editTargetPlanDay: jest.fn(),
  cancelTargetPlan: jest.fn(),
  parseTargetPlanPhoto: jest.fn(),
  previewPersonalTargetAudience: jest.fn(),
  fetchAllTargetProgress: jest.fn(),
  fetchStudentDayTimeline: jest.fn(),
  changeStudentStartDay: jest.fn(),
}));

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ok: true, build: 'test-build' }),
  });
  dailyTargetsApi.fetchTargetOptions.mockResolvedValue({
    attempts: ['Jan 27'],
    groups: ['Group I'],
    batches: ['May 2027'],
    subjects: ['Accounts'],
  });
  dailyTargetsApi.previewTargetAudience.mockResolvedValue({ count: 10 });
  targetPlansApi.fetchTargetPlans.mockResolvedValue({
    plans: [],
    capabilities: { aiPhotoReading: true },
  });
  targetPlansApi.fetchAllTargetProgress.mockResolvedValue({
    ok: true,
    maxDays: 40,
    total: 2,
    started: 1,
    notStarted: 1,
    rows: [
      {
        studentId: 'UMP0011',
        name: 'Aarav Sharma',
        batch: 'May 2027',
        group: 'Group I',
        attempt: 'May 27',
        started: true,
        startDay: 12,
        currentDay: 14,
        startDate: '2026-11-01',
        completedDays: 2,
        finished: false,
      },
      {
        studentId: 'UMP0022',
        name: 'Riya Verma',
        batch: 'Jan 2027',
        group: 'Group II',
        attempt: 'Jan 27',
        started: false,
        startDay: null,
        currentDay: null,
        startDate: null,
        completedDays: 0,
        finished: false,
      },
    ],
  });
  targetPlansApi.fetchStudentDayTimeline.mockResolvedValue({
    ok: true,
    studentId: 'UMP0011',
    startDay: 12,
    currentDay: 14,
    maxDays: 40,
    days: [
      { day: 12, plannedDate: '2026-11-01', beforeStart: false, state: 'complete', targetCount: 1, targets: [{ id: 't1', label: 'Accounts Ch 1' }] },
      { day: 13, plannedDate: '2026-11-02', beforeStart: false, state: 'complete', targetCount: 1, targets: [{ id: 't2', label: 'Accounts Ch 2' }] },
      { day: 14, plannedDate: '2026-11-03', beforeStart: false, state: 'open', targetCount: 1, targets: [{ id: 't3', label: 'Law Ch 1', detail: 'Contract Act' }] },
    ],
  });
  targetPlansApi.changeStudentStartDay.mockResolvedValue({ ok: true });
});

test('renders Student day progress, auto-opens Day timeline, and lets mentor change start day', async () => {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    await act(async () => {
      root.render(<TargetPlans />);
    });
    // Wait for async effects
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const progressPanel = host.querySelector('[data-testid="start-day-progress"]');
    expect(progressPanel).not.toBeNull();
    expect(progressPanel.textContent).toContain('Started 1');
    expect(progressPanel.textContent).toContain('Not started 1');
    expect(progressPanel.textContent).toContain('Aarav Sharma');
    expect(progressPanel.textContent).toContain('Day 12');
    expect(progressPanel.textContent).toContain('Day 14');

    const timelinePanel = host.querySelector('[data-testid="start-day-timeline"]');
    expect(timelinePanel).not.toBeNull();
    expect(timelinePanel.textContent).toContain('Day timeline · UMP0011');
    expect(timelinePanel.textContent).toContain('Law Ch 1');

    // Change UMP0022 start day to 8
    const input = host.querySelector('input[aria-label="Start day for UMP0022"]');
    expect(input).not.toBeNull();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '8');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const saveBtn = input.parentElement.querySelector('button');
    await act(async () => {
      saveBtn.click();
    });

    expect(targetPlansApi.changeStudentStartDay).toHaveBeenCalledWith(
      'UMP0022',
      8,
      'changed from Target Plans page'
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
