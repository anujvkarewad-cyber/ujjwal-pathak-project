import { useEffect, useRef, useState } from 'react';
import { apiCall } from '@/api/backendClient';

import { emptyQuestion, workbookPayload, cloneWorkbookQuestion, matchesWorkbookPayload } from './workbookAuthoring';
export { workbookPayload } from './workbookAuthoring';

export default function Workbooks() {
  const [form, setForm] = useState({ title: '', subject: 'Audit', groups: ['Group 2'], batches: '', sourceUrl: '' });
  const [questions, setQuestions] = useState([emptyQuestion()]);
  const [books, setBooks] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const draftIntent = useRef(null);
  const load = async () => {
    const data = await apiCall('/api/practice/mentor/workbooks');
    if (!Array.isArray(data?.workbooks)) throw new Error('Saved workbook readback was not confirmed. Your draft is unchanged.');
    setBooks(data.workbooks); return data.workbooks;
  };
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  const change = (i, key, value) => setQuestions(qs => qs.map((q, n) => n === i ? { ...q, [key]: value, ...(key !== 'sourceVerified' ? { sourceVerified: false } : {}) } : q));
  const action = async (fn) => { setBusy(true); setError(''); setMessage(''); try { setMessage(await fn()); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  const save = () => action(async () => {
    const payload = workbookPayload(form, questions), signature = JSON.stringify(payload);
    if (draftIntent.current?.signature !== signature) draftIntent.current = { signature, key: crypto.randomUUID() };
    const ack = await apiCall('/api/practice/mentor/workbooks', { method: 'POST', body: payload, params: { draftKey: draftIntent.current.key } });
    if (typeof ack?.id !== 'string' || !ack.id || ack.published !== false) throw new Error('Draft save was not confirmed. Keep this draft and review saved workbooks before retrying.');
    const saved = (await load()).find(b => b.id === ack.id);
    if (saved?.published !== false || !matchesWorkbookPayload(payload, saved)) throw new Error('Draft readback did not match. Your local draft is unchanged; review saved workbooks.');
    return 'Draft saved and read back. Review before publishing; no notification sent.';
  });
  const availability = book => action(async () => {
    const published = !book.published;
    const ack = await apiCall(`/api/practice/mentor/workbooks/${book.id}/${published ? 'publish' : 'unpublish'}`, { method: 'POST' });
    if (ack?.published !== published || ack.notificationsSent !== 0) throw new Error('Availability write was not confirmed. Review saved workbooks before retrying.');
    const saved = (await load()).find(b => b.id === book.id);
    if (saved?.published !== published) throw new Error('Availability readback did not match. Review saved workbooks before retrying.');
    return 'Availability updated and read back. No student notification sent.';
  });
  const clone = (book) => {
    try {
      const nextQuestions = book.questions.map(cloneWorkbookQuestion);
      setForm({ title: book.title, subject: book.subject, groups: book.groups, batches: (book.batches || []).join('\n'), sourceUrl: book.sourceUrl || '' });
      draftIntent.current = null; setQuestions(nextQuestions); setError(''); setMessage('Loaded as a new draft. Existing published version stays unchanged. Recheck every source and answer key.');
    } catch (e) { setError(e.message); }
  };
  const input = 'w-full rounded-lg border border-slate-300 bg-white p-3 text-slate-900';
  return <div className="space-y-6 max-w-5xl">
    <header><h1 className="text-2xl font-bold">Audit & SM workbooks</h1><p className="text-slate-500 mt-2">Written-answer practice with provisional AI feedback; objective formats use the approved answer key. No leaderboard or final exam marks.</p></header>
    <div className="rounded-xl bg-blue-50 p-4 text-sm text-blue-900">Use your existing workbook PDF link. Map each question to its supplied model answer and marks. Students type or write over rendered workbook pages; the original PDF is not overwritten. No audio answers here. Model-answer mapping is mentor-reviewed, not guessed from the PDF.</div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-700">{error}</p>}
    {message && <p role="status" className="rounded-lg bg-green-50 p-3 text-green-800">{message}</p>}
    <fieldset disabled={busy} className="space-y-4 rounded-xl border p-5">
      <label className="block">Workbook title<input aria-label="Workbook title" className={input} value={form.title} maxLength={160} onChange={e => setForm({ ...form, title: e.target.value })} /></label>
      <label className="block">Subject<select className={input} value={form.subject} onChange={e => { setForm({ ...form, subject: e.target.value }); setQuestions(qs => qs.map(q => ({ ...q, sourceVerified: false }))); }}><option>Audit</option><option>SM</option></select></label>
      <div>Assigned groups <span className="text-xs text-slate-500">(Both is its own group, not a union)</span><div className="flex gap-5">{['Group 1', 'Group 2', 'Both'].map(g => <label key={g}><input type="checkbox" checked={form.groups.includes(g)} onChange={e => setForm({ ...form, groups: e.target.checked ? [...form.groups, g] : form.groups.filter(x => x !== g) })} /> {g}</label>)}</div></div>
      <label className="block">Batches, one exact name per line (empty = all selected groups)<textarea className={input} value={form.batches} onChange={e => setForm({ ...form, batches: e.target.value })} /></label>
      <label className="block">Existing PDF link (optional HTTPS Google Drive/Storage)<input type="url" className={input} value={form.sourceUrl} onChange={e => { setForm({ ...form, sourceUrl: e.target.value }); setQuestions(qs => qs.map(q => ({ ...q, sourceVerified: false }))); }} /></label>
      {questions.map((q, i) => <section key={i} className="space-y-3 border rounded-xl p-4 bg-slate-50">
        <h2 className="font-bold">Question {i + 1}</h2>
        <label className="block">Question format<select aria-label={`Question format ${i + 1}`} className={input} value={q.format || 'written'} onChange={e => change(i, 'format', e.target.value)}><option value="written">Written answer — meaning-based feedback</option><option value="mcq">MCQ — one approved option</option><option value="blanks">Fill in the blanks — approved answers/aliases</option><option value="matching">Matching — one-to-one approved key</option></select></label>
        {q.format === 'mcq' && <div className="space-y-3">
          <label className="block">MCQ options: one <code>option ID | displayed text</code> per line<textarea aria-label={`MCQ options ${i + 1}`} className={input} rows={4} value={q.optionsText} onChange={e => change(i, 'optionsText', e.target.value)} /></label>
          <label className="block">Approved correct option ID<input aria-label={`Correct option ID ${i + 1}`} className={input} value={q.correctOptionId} maxLength={40} onChange={e => change(i, 'correctOptionId', e.target.value)} /></label>
          <p className="text-sm text-slate-600">Provide exactly one rubric/mark line for this MCQ. The student listing does not expose this key.</p>
        </div>}
        {q.format === 'blanks' && <label className="block">Blank keys: one <code>displayed blank label | approved answer ;; optional alias</code> per rubric point, in the same order<textarea aria-label={`Blank keys ${i + 1}`} className={input} rows={5} value={q.blanksText} onChange={e => change(i, 'blanksText', e.target.value)} /><span className="text-sm text-slate-600">Only explicitly entered aliases receive credit. Do not infer answers or marks from chapter weightage.</span></label>}
        {q.format === 'matching' && <div className="space-y-3">
          <label className="block">Right options: one <code>option ID | displayed text</code> per line<textarea aria-label={`Matching right options ${i + 1}`} className={input} rows={4} value={q.matchingRightText} onChange={e => change(i, 'matchingRightText', e.target.value)} /></label>
          <label className="block">Left items: one <code>displayed text | approved right-option ID</code> per rubric point, in the same order<textarea aria-label={`Matching left keys ${i + 1}`} className={input} rows={4} value={q.matchingLeftText} onChange={e => change(i, 'matchingLeftText', e.target.value)} /></label>
          <p className="text-sm text-slate-600">Use every right option once; enter the explicit approved marks in the rubric below.</p>
        </div>}
        <label className="block">Question text<textarea className={input} value={q.prompt} maxLength={5000} onChange={e => change(i, 'prompt', e.target.value)} /></label>
        <label className="block">Supplied model answer<textarea rows={5} className={input} value={q.modelAnswer} maxLength={12000} onChange={e => change(i, 'modelAnswer', e.target.value)} /></label>
        <div className="grid grid-cols-2 gap-3"><label>Model-answer source / edition<input className={input} value={q.referenceLabel} onChange={e => change(i, 'referenceLabel', e.target.value)} /></label><label>Reference page<input className={input} type="number" min="1" max="1000" value={q.page} onChange={e => change(i, 'page', e.target.value)} /></label></div>
        <label className="block">Workbook PDF page for this question<input className={input} type="number" min="1" max="400" value={q.workbookPage || 1} onChange={e => change(i, 'workbookPage', e.target.value)} /></label>
        <label className="block">Rubric: one line per concept, <code>marks | concept to credit</code><textarea rows={4} className={input} placeholder="2 | Explain the relevant principle in equivalent words" value={q.rubricText} onChange={e => change(i, 'rubricText', e.target.value)} /></label>
        <label className="flex items-start gap-2"><input type="checkbox" checked={q.sourceVerified} onChange={e => change(i, 'sourceVerified', e.target.checked)} /><span>I checked this question, model answer, objective key/aliases where applicable, reference and mark allocation against the supplied source.</span></label>
        {questions.length > 1 && <button type="button" onClick={() => setQuestions(qs => qs.filter((_, n) => n !== i))}>Remove question</button>}
      </section>)}
      <div className="flex gap-3"><button className="border rounded-lg p-3" onClick={() => setQuestions(qs => [...qs, emptyQuestion()])} disabled={questions.length >= 60}>Add question</button><button className="rounded-lg p-3 bg-blue-700 text-white" onClick={save}>Save draft — not publish</button></div>
    </fieldset>
    <div className="flex flex-wrap gap-3 items-center justify-between"><h2 className="text-xl font-bold">Saved workbooks</h2><button disabled={busy} className="border rounded-lg p-2" onClick={() => action(async () => { await load(); return 'Saved workbook list refreshed. Your current draft is unchanged.'; })}>Refresh saved workbooks</button></div>
    {books.map(book => <article className="rounded-xl border p-4 flex flex-wrap gap-3 justify-between" key={book.id}><div><strong>{book.title}</strong><p>{book.subject} · {book.questions.length} questions · {book.published ? 'Published' : 'Draft'}</p></div><div className="flex gap-3"><button disabled={busy} onClick={() => clone(book)}>Copy to new draft</button><button disabled={busy} onClick={() => availability(book)}>{book.published ? 'Unpublish' : 'Publish without notification'}</button></div></article>)}
  </div>;
}
