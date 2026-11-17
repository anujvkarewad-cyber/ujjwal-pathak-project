import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import BatchDriftCard from './BatchDriftCard';
import { applyBatchDrift, getBatchDrift, importMissingAccounts } from '@/api/studentAdmin';

jest.mock('react-router-dom', () => ({
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
}), { virtual: true });

jest.mock('@/api/studentAdmin', () => ({
  applyBatchDrift: jest.fn(),
  getBatchDrift: jest.fn(),
  importMissingAccounts: jest.fn(),
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

const missing = [
  { studentId: 'UMP9965', studentName: 'Suha Khan', sheetBatch: 'After Result Batch 2' },
  { studentId: 'UMP9968', studentName: 'Fatima Nadeem', sheetBatch: 'After Result Batch 1' },
];
let host;
let root;
let queryClient;
let confirmSpy;

beforeEach(() => {
  jest.clearAllMocks();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  getBatchDrift.mockResolvedValue({ drift: [], needsImport: missing, checkedAt: '2026-11-17T10:20:00Z' });
  importMissingAccounts.mockResolvedValue({
    ok: true,
    createdCount: 2,
    skippedCount: 0,
    failedCount: 0,
    message: 'Added 2 app accounts; no email was sent.',
  });
  confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  confirmSpy.mockRestore();
});

async function mount() {
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <BatchDriftCard />
      </QueryClientProvider>,
    );
  });
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

function importButton() {
  return host.querySelector('[data-testid="batch-drift-import-missing"]');
}

test('shows an explicit add button and imports only the listed IDs after confirmation', async () => {
  await mount();
  expect(importButton()).toBeTruthy();
  expect(importButton().textContent).toContain('Add 2 to app');

  await act(async () => {
    importButton().click();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('UMP9965'));
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('UMP9968'));
  expect(importMissingAccounts).toHaveBeenCalledWith(['UMP9965', 'UMP9968']);
  expect(importMissingAccounts.mock.calls[0][0]).not.toContain('password');
  expect(applyBatchDrift).not.toHaveBeenCalled();
});

test('canceling the confirmation does not call the import endpoint', async () => {
  confirmSpy.mockReturnValue(false);
  await mount();

  await act(async () => importButton().click());

  expect(confirmSpy).toHaveBeenCalledTimes(1);
  expect(importMissingAccounts).not.toHaveBeenCalled();
});
