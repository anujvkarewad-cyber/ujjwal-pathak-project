import { TextEncoder, TextDecoder } from 'util';
import { prepareNote, originalEntry, selectedNoteFile, preparedMatches, preparationMessage, preparationWithinBudget } from './notePreparation';

jest.mock('./backendClient', () => ({ apiUrl: path => path, getToken: () => '', AUTH_EVENT: 'upm:auth-required' }));
beforeAll(() => { global.TextEncoder = TextEncoder; global.TextDecoder = TextDecoder; });
const original = () => new File(['%PDF-1.7\n' + 'x'.repeat(6000)], 'Accounts.pdf', { type: 'application/pdf', lastModified: 123 });
function response(file, { status=200, kind='application/pdf', compressed=true, mismatch=false } = {}) {
  const content = new TextEncoder().encode('%PDF-1.7\noptimized mock bytes');
  const headers = { 'content-type':kind, 'x-notes-status':compressed ? 'compressed' : 'original',
    'x-notes-reason': compressed ? 'optimized' : 'no_meaningful_saving',
    'x-notes-original-bytes': String(mismatch ? 1 : file.size), 'x-notes-output-bytes':String(content.byteLength) };
  return { status, ok: status === 200, headers: { get: key => headers[key] || null }, arrayBuffer: async () => content.buffer };
}

test('selects prepared bytes while preserving name and original object', async () => {
  const file=original();const fetchImpl=jest.fn(async()=>response(file));
  const result=await prepareNote(file,{fetchImpl});
  expect(result.original).toBe(file);expect(result.file.name).toBe(file.name);
  expect(result.file.size).toBeLessThan(file.size);expect(result.useOriginal).toBe(false);
  expect(selectedNoteFile(result)).toBe(result.file);
  expect(fetchImpl.mock.calls[0][0]).toBe('/api/mentor/notes/prepare?quality=balanced');
  expect(fetchImpl.mock.calls[0][1].body).toBe(file);
});

test('original selection returns exact local file without relying on server copy',()=>{
  const file=original();expect(selectedNoteFile(originalEntry(file))).toBe(file);
});

test('per-file original override is respected',async()=>{
  const file=original();const entry=await prepareNote(file,{fetchImpl:async()=>response(file)});
  expect(selectedNoteFile({...entry,useOriginal:true})).toBe(file);
});

for (const [name, options] of [ ['busy',{status:429}],['old server',{status:404}],['HTML fallback',{kind:'text/html'}],['wrong size',{mismatch:true}],['no saving',{compressed:false}] ]) {
  test(name+' retains original with visible reason',async()=>{
    const file=original();const result=await prepareNote(file,{fetchImpl:async()=>response(file,options)});
    expect(selectedNoteFile(result)).toBe(file);expect(result.status).toBe('original');
    expect(preparationMessage(result.reason)).toMatch(/original/i);
  });
}

test('network failure retains original',async()=>{
  const file=original();const result=await prepareNote(file,{fetchImpl:async()=>{throw new Error('offline');}});
  expect(result.reason).toBe('preparation_unavailable');expect(selectedNoteFile(result)).toBe(file);
});

test.each([401,403])('auth %i stops rather than bypassing into original upload',async status=>{
  const file=original();await expect(prepareNote(file,{fetchImpl:async()=>response(file,{status})})).rejects.toMatchObject({authRequired:true});
});

test('401 notifies existing auth handler',async()=>{
  const fn=jest.fn();window.addEventListener('upm:auth-required',fn);
  const file=original();await prepareNote(file,{fetchImpl:async()=>response(file,{status:401})}).catch(()=>{});
  expect(fn).toHaveBeenCalledTimes(1);window.removeEventListener('upm:auth-required',fn);
});

test('cancel aborts preparation rather than allowing late stale data',async()=>{
  const controller=new AbortController();controller.abort();
  const file=original();await expect(prepareNote(file,{signal:controller.signal,fetchImpl:async()=>{throw new DOMException('Aborted','AbortError');}})).rejects.toMatchObject({name:'AbortError'});
});

test('prepared results cannot be applied to a changed file selection',()=>{
  const file=original();expect(preparedMatches([file],[originalEntry(file)])).toBe(true);
  expect(preparedMatches([original()],[originalEntry(file)])).toBe(false);
  expect(preparedMatches([file],[])).toBe(false);expect(preparedMatches([],[])).toBe(false);
});

test('unknown failure text is not echoed to the mentor',()=>{
  expect(preparationMessage('<script>private PDF content</script>')).not.toContain('script');
});


test('preparation budget bounds retained preview memory',()=>{
  expect(preparationWithinBudget(Array.from({length:25},()=>({size:1024})))).toBe(true);
  expect(preparationWithinBudget(Array.from({length:26},()=>({size:1024})))).toBe(false);
});

test('preparation budget limits aggregate bytes independently of file count',()=>{
  expect(preparationWithinBudget([{size:100*1024*1024}])).toBe(true);
  expect(preparationWithinBudget([{size:100*1024*1024+1}])).toBe(false);
});
