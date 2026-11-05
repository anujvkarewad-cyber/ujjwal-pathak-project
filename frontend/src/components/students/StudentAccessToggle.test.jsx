import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import StudentAccessToggle from './StudentAccessToggle';
import { setStudentAccess } from '@/api/studentAdmin';

jest.mock('@/api/studentAdmin', () => ({ setStudentAccess: jest.fn() }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

global.IS_REACT_ACT_ENVIRONMENT = true;

let host, root;
const click = (el) => act(async () => { el.click(); });
const type = (el, value) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
});

beforeEach(() => {
  jest.clearAllMocks();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  setStudentAccess.mockResolvedValue({ ok: true, accessEnabled: false });
});

afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

async function mount(props = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => root.render(
    <QueryClientProvider client={qc}>
      <StudentAccessToggle studentId="UMP0025" studentName="Diksha Hemant Nemade" {...props} />
    </QueryClientProvider>,
  ));
}

test('turning access off needs a reason, and sends it with the student id', async () => {
  await mount({ enabled: true });
  expect(host.querySelector('[data-testid="access-toggle-UMP0025"]').textContent).toContain('ON');

  await click(host.querySelector('[data-testid="access-toggle-UMP0025"]'));
  const confirm = host.querySelector('[data-testid="access-confirm-UMP0025"]');
  expect(confirm.disabled).toBe(true);
  expect(setStudentAccess).not.toHaveBeenCalled();

  await type(host.querySelector('[data-testid="access-reason-UMP0025"]'), 'Stopped attending');
  expect(host.querySelector('[data-testid="access-confirm-UMP0025"]').disabled).toBe(false);
  await click(host.querySelector('[data-testid="access-confirm-UMP0025"]'));

  expect(setStudentAccess).toHaveBeenCalledWith('UMP0025', false, 'Stopped attending');
});

test('cancelling the reason box leaves access untouched', async () => {
  await mount({ enabled: true });
  await click(host.querySelector('[data-testid="access-toggle-UMP0025"]'));
  await click(host.querySelector('[data-testid="access-cancel-UMP0025"]'));
  expect(setStudentAccess).not.toHaveBeenCalled();
  expect(host.querySelector('[data-testid="access-toggle-UMP0025"]')).not.toBeNull();
});

test('a blocked student is turned back on in one action, with no reason', async () => {
  await mount({ enabled: false });
  expect(host.querySelector('[data-testid="access-toggle-UMP0025"]').textContent).toContain('OFF');

  await click(host.querySelector('[data-testid="access-toggle-UMP0025"]'));

  expect(setStudentAccess).toHaveBeenCalledWith('UMP0025', true, '');
  expect(host.querySelector('[data-testid="access-reason-UMP0025"]')).toBeNull();
});

test('a student with no app account shows no switch at all', async () => {
  await mount({ enabled: true, known: false });
  expect(host.querySelector('[data-testid="access-toggle-UMP0025"]')).toBeNull();
  expect(host.querySelector('[data-testid="access-unavailable-UMP0025"]')).not.toBeNull();
});
