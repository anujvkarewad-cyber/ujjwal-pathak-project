import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import Notes from './Notes';
import { prepareNote } from '../api/notePreparation';
import { createNoteChunked } from '../api/notes';

jest.mock('@/api/hooks', () => ({
  useNotes: () => ({data:[],isLoading:false}),
  useDeleteNote: () => ({mutateAsync:jest.fn()}),
  useUpdateNote: () => ({mutateAsync:jest.fn()}),
}));
jest.mock('@tanstack/react-query', () => ({useQueryClient:()=>({invalidateQueries:jest.fn()})}));
jest.mock('@/api/notes',()=>({createNoteChunked:jest.fn(),bulkUpdateNotes:jest.fn()}));
jest.mock('@/api/notePreparation',()=>({
  ...jest.requireActual('@/api/notePreparation'), prepareNote:jest.fn(),
}));
let root,container;
beforeEach(()=>{
  global.IS_REACT_ACT_ENVIRONMENT=true;
  URL.createObjectURL=jest.fn(()=> 'blob:test-preview');URL.revokeObjectURL=jest.fn();
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
  prepareNote.mockReset();createNoteChunked.mockReset();createNoteChunked.mockResolvedValue({ok:true});
  act(()=>root.render(<Notes/>));
});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function select(file) {
  const input=container.querySelector('#note-file');
  Object.defineProperty(input,'files',{value:[file],configurable:true});
  await act(async()=>input.dispatchEvent(new Event('change',{bubbles:true})));
}
const file=()=>new File(['%PDF-original '+ 'X'.repeat(2000)],'Law_notes.pdf',{type:'application/pdf'});
async function submit() {
  await act(async()=>{
    container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
    await new Promise(resolve=>setTimeout(resolve,60));
  });
}
async function prepare() {
  const button=[...container.querySelectorAll('button')].find(b=>b.textContent.includes('Prepare PDFs'));
  await act(async()=>button.click());
}

test('balanced starts locked; preparation does not publish',async()=>{
  const original=file();prepareNote.mockResolvedValue({original,file:original,status:'original',reason:'no_meaningful_saving',useOriginal:true});
  await select(original);
  expect(container.querySelector('[data-testid="publish-note"]').disabled).toBe(true);
  await prepare();
  expect(createNoteChunked).not.toHaveBeenCalled();
  expect(container.querySelector('[data-testid="publish-note"]').disabled).toBe(false);
});

test('balanced upload uses reviewed compressed bytes and preserves routing metadata',async()=>{
  const original=file();const compressed=new File(['%PDF-optimized'],original.name,{type:'application/pdf'});
  prepareNote.mockResolvedValue({original,file:compressed,status:'compressed',reason:'optimized',useOriginal:false});
  await select(original);await prepare();await submit();
  expect(createNoteChunked).toHaveBeenCalledTimes(1);
  const payload=createNoteChunked.mock.calls[0][0];
  expect(atob(payload.fileData)).toBe('%PDF-optimized');expect(payload.fileName).toBe('Law_notes.pdf');
  expect(payload.audience).toBeTruthy();expect(payload.group).toBeTruthy();expect(payload.subject).toBeTruthy();
  expect(container.textContent).toContain('Uploaded successfully');
});

test('per-file original override uploads original bytes',async()=>{
  const original=file();prepareNote.mockResolvedValue({original,file:new File(['%PDF-small'],original.name),status:'compressed',reason:'optimized',useOriginal:false});
  await select(original);await prepare();
  const checkbox=container.querySelector('input[type="checkbox"]');
  await act(async()=>checkbox.click());await submit();
  expect(atob(createNoteChunked.mock.calls[0][0].fileData)).toContain('%PDF-original');
});

test('Original quality bypasses optimizer, not existing uploader',async()=>{
  await select(file());
  await act(async()=>{const quality=container.querySelector('#notes-quality');quality.value='original';quality.dispatchEvent(new Event('change',{bubbles:true}));});
  await submit();expect(prepareNote).not.toHaveBeenCalled();expect(createNoteChunked).toHaveBeenCalledTimes(1);
});

test('preparation authentication error keeps upload locked',async()=>{
  prepareNote.mockRejectedValue(new Error('Mentor authentication required'));
  await select(file());await prepare();
  expect(container.textContent).toContain('Mentor authentication required');
  expect(container.querySelector('[data-testid="publish-note"]').disabled).toBe(true);
  expect(createNoteChunked).not.toHaveBeenCalled();
});
