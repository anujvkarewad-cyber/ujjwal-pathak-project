import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import TestAuthoring from './TestAuthoring';
import {
  createMentorTest,
  listMentorTests,
  updateMentorTest,
} from '@/api/mentorTestsAdmin';

jest.mock('@/api/mentorTestsAdmin', () => ({
  createMentorTest: jest.fn(),
  deleteMentorTest: jest.fn(),
  formatBytes: jest.fn((bytes) => `${bytes} bytes`),
  listMentorTests: jest.fn(),
  setMentorTestPublished: jest.fn(),
  updateMentorTest: jest.fn(),
  uploadTestFile: jest.fn(),
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

let host;
let root;
const COST_CHAPTER = 'Ch 1 — Introduction to Cost and Management Accounting';
const ACCOUNT_CHAPTER = 'Ch 1 — Introduction to Accounting Standards';

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  listMentorTests.mockReset().mockResolvedValue({ items: [] });
  createMentorTest.mockReset().mockResolvedValue({ test: { title: `Practice test — ${COST_CHAPTER}` } });
  updateMentorTest.mockReset().mockResolvedValue({ ok: true });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function renderAuthoring() {
  await act(async () => {
    root.render(<TestAuthoring />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(element) {
  await act(async () => element.click());
}

async function changeSelect(element, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(element, value);
    element.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function chapterCheckbox(chapter) {
  const inputs = [...host.querySelectorAll('input[type="checkbox"][data-testid^="test-chapter-"]')];
  return inputs.find((input) => input.getAttribute('data-testid') === `test-chapter-${chapter}`) || null;
}

test('the test name is optional while at least one subject chapter is required', async () => {
  await renderAuthoring();
  await click(host.querySelector('[data-testid="create-test"]'));

  const title = host.querySelector('[data-testid="test-title"]');
  expect(title).not.toBeNull();
  expect(title.required).toBe(false);
  expect(host.textContent).toContain('Optional. Leave blank');
  expect(host.querySelector('[data-testid="test-chapter-group"]').getAttribute('aria-required')).toBe('true');
  expect(chapterCheckbox(COST_CHAPTER)).not.toBeNull();
  expect(chapterCheckbox(ACCOUNT_CHAPTER)).toBeNull();

  await click(host.querySelector('[data-testid="save-test"]'));
  expect(host.querySelector('[role="alert"]').textContent).toContain('Choose at least one chapter');
  expect(createMentorTest).not.toHaveBeenCalled();
});

test('changing the subject filters its chapters and clears the previous selection', async () => {
  await renderAuthoring();
  await click(host.querySelector('[data-testid="create-test"]'));
  await click(chapterCheckbox(COST_CHAPTER));
  expect(chapterCheckbox(COST_CHAPTER).checked).toBe(true);
  expect(host.textContent).toContain(`Materials under Costing → ${COST_CHAPTER}`);

  await changeSelect(host.querySelector('[data-testid="test-subject"]'), 'Accounts');
  expect(chapterCheckbox(COST_CHAPTER)).toBeNull();
  expect(chapterCheckbox(ACCOUNT_CHAPTER)).not.toBeNull();
  expect(chapterCheckbox(ACCOUNT_CHAPTER).checked).toBe(false);
  expect(host.textContent).toContain('Choose at least one chapter for this subject');
});

test('saving with a blank manual name stores the selected chapter and derives a test title', async () => {
  await renderAuthoring();
  await click(host.querySelector('[data-testid="create-test"]'));
  await click(chapterCheckbox(COST_CHAPTER));
  await click(host.querySelector('[data-testid="save-test"]'));

  expect(createMentorTest).toHaveBeenCalledTimes(1);
  expect(createMentorTest.mock.calls[0][0]).toEqual(expect.objectContaining({
    title: '',
    subject: 'Costing',
    chapters: [COST_CHAPTER],
  }));
  expect(host.textContent).toContain(`Practice test — ${COST_CHAPTER}`);
});
