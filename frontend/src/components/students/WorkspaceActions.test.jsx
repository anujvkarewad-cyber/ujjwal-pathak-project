import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import WorkspaceActions from './WorkspaceActions';
import { reviewWorkspaceOperation, sendWorkspaceNow, commitWorkspaceOperation, getWorkspacePlan, reconcileWorkspacePlan, getWorkspaceAnnouncements } from '@/api/mentorWorkspace';
jest.mock('@/api/mentorWorkspace', () => ({
  reviewWorkspaceOperation: jest.fn(), sendWorkspaceNow: jest.fn(), commitWorkspaceOperation: jest.fn(),
  getWorkspacePlan: jest.fn(), reconcileWorkspacePlan: jest.fn(), getWorkspaceAnnouncements: jest.fn(),
}));
global.IS_REACT_ACT_ENVIRONMENT = true;
const students = [{ id: 'UMP0001', name: 'Test Student', batch: 'Existing batch', group: 'Group 1', membershipConsistent: true }];
let host, root;
const click = async el => act(async () => { el.click(); });
const button = text => [...host.querySelectorAll('button')].find(b => b.textContent === text);
const plan = { planId: 'test-review', kind: 'message', recipients: students };
beforeEach(() => {
  jest.clearAllMocks(); sessionStorage.clear();
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host);
  reviewWorkspaceOperation.mockResolvedValue(plan);
  sendWorkspaceNow.mockResolvedValue({ ...plan, direct: true, state: 'completed', outcomes: [{ studentId: 'UMP0001', state: 'completed' }] });
  commitWorkspaceOperation.mockResolvedValue({ state: 'completed', outcomes: [{ studentId: 'UMP0001', state: 'completed' }] });
  getWorkspaceAnnouncements.mockResolvedValue({ announcements: [] });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function mount(props = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => root.render(<QueryClientProvider client={qc}><WorkspaceActions students={students} batch="Existing batch" group="group1" batches={['Existing batch', 'Existing second batch']} {...props} /></QueryClientProvider>));
}
async function type(selector, value) {
  const el = host.querySelector(selector);
  await act(async () => {
    Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function choose(selector, value) {
  const el = host.querySelector(selector);
  await act(async () => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

test('a private message needs a selection and then sends in one action, with no confirmation step', async () => {
  await mount();
  await click(button('Send now'));
  expect(sendWorkspaceNow).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Select at least one student.');
  await click(host.querySelectorAll('input[type="checkbox"]')[1]);
  await type('textarea', 'Private guidance');
  await click(button('Send now'));
  expect(sendWorkspaceNow).toHaveBeenCalledWith(expect.objectContaining({ kind: 'message', studentIds: ['UMP0001'], scopes: [{ batch: 'Existing batch', group: 'group1' }], text: 'Private guidance' }));
  expect(reviewWorkspaceOperation).not.toHaveBeenCalled();
  expect(commitWorkspaceOperation).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('upm_workspace_pending_plan')).toBeNull();
  expect(host.textContent).toContain('Outcome: completed');
});

test('an unknown transfer commit outcome blocks resend and preserves the status reference', async () => {
  commitWorkspaceOperation.mockRejectedValue(new Error('Network outcome unknown'));
  reviewWorkspaceOperation.mockResolvedValue({
    ...plan,
    kind: 'transfer',
    destination: { batch: 'Before Result Batch 2', group: 'group1' },
  });
  await mount({ focusStudentId: 'UMP0001', initialKind: 'transfer' });
  await choose('select[aria-label="Destination batch"]', 'Before Result Batch 2');
  await click(button('Review recipients & changes'));
  await click(button('Confirm transfer'));
  expect(sessionStorage.getItem('upm_workspace_pending_plan')).toBe('test-review');
  expect(button('Review recipients & changes').disabled).toBe(true);
  expect(host.textContent).toContain('Do not resend');
  expect(commitWorkspaceOperation).toHaveBeenCalledTimes(1);
  getWorkspacePlan.mockResolvedValue({ state: 'partial', body: { kind: 'transfer' }, outcomes: [] });
  await click(button('Check outcome'));
  expect(button('Reconcile transfer readback')).toBeDefined();
});

test('a partial transfer is not retried; reconciliation is a separate explicit action', async () => {
  sessionStorage.setItem('upm_workspace_pending_plan', 'old-partial');
  getWorkspacePlan.mockResolvedValue({ state: 'partial', body: { kind: 'transfer' }, outcomes: [{ studentId: 'UMP0001', state: 'needs_reconciliation' }] });
  reconcileWorkspacePlan.mockResolvedValue({ state: 'reconciled', outcomes: [{ studentId: 'UMP0001', state: 'not_applied' }] });
  await mount();
  await click(button('Check outcome'));
  expect(commitWorkspaceOperation).not.toHaveBeenCalled();
  await click(button('Reconcile transfer readback'));
  expect(reconcileWorkspacePlan).toHaveBeenCalledWith('old-partial');
  expect(sessionStorage.getItem('upm_workspace_pending_plan')).toBeNull();
});

test('an announcement carries explicit exclusive targets, not an unscoped broadcast, and sends in one action', async () => {
  sendWorkspaceNow.mockResolvedValue({ ...plan, kind: 'announcement', direct: true, state: 'completed', outcomes: [] });
  await mount({ mode: 'announcements' });
  await type('input[aria-label="Announcement title"]', 'Update');
  await type('textarea', 'App only');
  await click(button('Send now'));
  expect(sendWorkspaceNow).toHaveBeenCalledWith(expect.objectContaining({ kind: 'announcement', scopes: [{ batch: 'Existing batch', group: 'group1' }], studentIds: [] }));
  expect(reviewWorkspaceOperation).not.toHaveBeenCalled();
  expect(commitWorkspaceOperation).not.toHaveBeenCalled();
});

test('partial communication outcomes never offer transfer reconciliation or resend', async () => {
  sessionStorage.setItem('upm_workspace_pending_plan', 'partial-message');
  getWorkspacePlan.mockResolvedValue({ state: 'partial', body: { kind: 'message' }, outcomes: [] });
  await mount(); await click(button('Check outcome'));
  expect(button('Reconcile transfer readback')).toBeUndefined();
  expect(commitWorkspaceOperation).not.toHaveBeenCalled();
});

test('transfer requires an explicit destination from the approved enrollment list', async () => {
  await mount({ focusStudentId: 'UMP0001', initialKind: 'transfer' });
  await click(button('Review recipients & changes'));
  expect(reviewWorkspaceOperation).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Choose a valid enrollment batch.');
});

test('profile transfer uses the exact approved destination labels, including the classes batch', async () => {
  await mount({ focusStudentId: 'UMP0001', initialKind: 'transfer' });
  await choose('select[aria-label="Destination batch"]', 'After Result Batch 1 with Classes');
  await click(button('Review recipients & changes'));
  expect(reviewWorkspaceOperation).toHaveBeenCalledWith(expect.objectContaining({
    kind: 'transfer',
    studentIds: ['UMP0001'],
    scopes: [],
    destination: { batch: 'After Result Batch 1 with Classes', group: 'group1' },
  }));
  expect(commitWorkspaceOperation).not.toHaveBeenCalled();
});
