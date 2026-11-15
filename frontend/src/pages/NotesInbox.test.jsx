import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import NotesInbox from './NotesInbox';
import { getInbox, publishInboxFile, skipInboxFile } from '@/api/notesInbox';
import { getNotes, updateNote } from '@/api/notes';

jest.mock('@/api/notesInbox', () => ({
  getInbox: jest.fn(),
  publishInboxFile: jest.fn(),
  skipInboxFile: jest.fn(),
}));

jest.mock('@/api/notes', () => ({
  getNotes: jest.fn(),
  updateNote: jest.fn(),
}));

let root;
let container;

const firstBatch = 'Before Result Batch 1';
const secondBatch = 'Before Result Batch 2';
const existingNote = {
  id: 'note-1',
  title: 'Accounts Chapter 1',
  fileName: 'accounts-chapter-1.pdf',
  fileId: 'drive-file-1',
  fileUrl: 'https://drive.google.com/file/d/drive-file-1/view',
  audience: firstBatch,
  batches: [firstBatch],
  group: 'Group 1',
  subject: 'Accounts',
  series: 'Super 75',
  chapter: 'Ch 1 — Introduction',
};

const flush = async () => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
};

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  getInbox.mockReset().mockResolvedValue({ files: [] });
  publishInboxFile.mockReset().mockResolvedValue({ ok: true });
  skipInboxFile.mockReset().mockResolvedValue({ ok: true });
  getNotes.mockReset().mockResolvedValue([existingNote]);
  updateNote.mockReset().mockResolvedValue({ ok: true });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderInbox() {
  await act(async () => {
    root.render(<NotesInbox />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test('shows previously published files below the waiting inbox', async () => {
  getNotes.mockResolvedValue([existingNote]);
  await renderInbox();

  expect(container.textContent).toContain('Inbox is empty — no files waiting.');
  expect(container.textContent).toContain('Published files (1)');
  expect(container.textContent).toContain('Accounts Chapter 1');
  expect(container.textContent).toContain(firstBatch);
});

test('publishing a waiting file refreshes it into the Published files section', async () => {
  const newlyPublished = {
    ...existingNote,
    id: 'note-new',
    title: 'New Law Notes',
    fileId: 'drive-new',
    fileName: 'law-notes.pdf',
  };
  getInbox
    .mockResolvedValueOnce({ files: [{ id: 'drive-new', name: 'law-notes.pdf', size: 1024, modifiedTime: '2026-11-01T00:00:00Z' }] })
    .mockResolvedValue({ files: [] });
  getNotes
    .mockResolvedValueOnce([])
    .mockResolvedValue([newlyPublished]);

  await renderInbox();
  expect(container.textContent).toContain('Name of file: law-notes.pdf');
  const publishButton = [...container.querySelectorAll('button')].find((button) => button.textContent.includes('Publish'));
  await act(async () => {
    publishButton.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  expect(publishInboxFile).toHaveBeenCalledWith(expect.objectContaining({ fileId: 'drive-new' }));
  expect(container.textContent).toContain('New Law Notes');
  expect(container.textContent).toContain('Published files (1)');
});

test('editing a published note adds another batch to the same file without republishing', async () => {
  getNotes.mockResolvedValue([existingNote]);
  await renderInbox();

  const editButton = container.querySelector('[data-testid="edit-published-note-1"]');
  await act(async () => editButton.click());

  const addBatch = container.querySelector(`[data-testid="published-batch-note-1-${secondBatch}"]`);
  await act(async () => addBatch.click());
  const saveButton = container.querySelector('[data-testid="save-published-note-1"]');
  await act(async () => {
    saveButton.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  expect(updateNote).toHaveBeenCalledWith('note-1', {
    batches: [firstBatch, secondBatch],
    group: 'Group 1',
  });
  expect(publishInboxFile).not.toHaveBeenCalled();
  expect(container.textContent).toContain('Wahi published file update hui');
});
