import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { reviewWorkspaceOperation, commitWorkspaceOperation, getWorkspacePlan, getWorkspaceAnnouncements, reconcileWorkspacePlan } from '@/api/mentorWorkspace';

const cls = 'rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900';
const pendingKey = 'upm_workspace_pending_plan';
function readPending() { try { return sessionStorage.getItem(pendingKey) || ''; } catch { return ''; } }
function storePending(id) { try { id ? sessionStorage.setItem(pendingKey, id) : sessionStorage.removeItem(pendingKey); } catch { /* server remains authoritative */ } }
export default function WorkspaceActions({ students, batch, group, mode = 'students', batches = [], focusStudentId, initialKind, initialText }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState(focusStudentId && students.some(s => s.id === focusStudentId) ? [focusStudentId] : []);
  const [announcementTargets, setAnnouncementTargets] = useState([batch + '|' + group]);
  const [kind, setKind] = useState(initialKind === 'transfer' && mode === 'students' ? 'transfer' : mode === 'announcements' ? 'announcement' : 'message');
  const [text, setText] = useState(initialText || '');
  const [title, setTitle] = useState('');
  const [destinationBatch, setDestinationBatch] = useState(batch);
  const [destinationGroup, setDestinationGroup] = useState(group);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [pending, setPending] = useState(readPending);
  const announcements = useQuery({ queryKey: ['workspace-announcements'], queryFn: getWorkspaceAnnouncements, enabled: mode === 'announcements' });
  const batchOptions = [...new Set([batch, ...batches])];
  const prepare = async () => {
    setError(''); setResult(null);
    if (pending) { setError('Check the previous operation outcome before preparing another send/transfer.'); return; }
    if (kind !== 'announcement' && !selected.length) { setError('Select at least one student.'); return; }
    setBusy(true);
    try {
      const body = { kind, studentIds: kind === 'announcement' ? [] : selected, scopes: kind === 'transfer' ? [] : kind === 'announcement' ? announcementTargets.map(t => { const i = t.lastIndexOf('|'); return { batch: t.slice(0, i), group: t.slice(i + 1) }; }) : [{ batch, group }], text, title };
      if (kind === 'transfer') body.destination = { batch: destinationBatch, group: destinationGroup };
      setReview(await reviewWorkspaceOperation(body));
    } catch (e) { setError(e.message || 'Recipient review failed. Nothing sent.'); }
    finally { setBusy(false); }
  };
  const invalidate = () => {
    ['workspace-roster', 'students', 'student', 'dashboard', 'tracker', 'leaderboard', 'workspace-announcements', 'announcements'].forEach(key => qc.invalidateQueries({ queryKey: [key] }));
  };
  const finish = data => {
    setResult({ ...data, kind: data.kind || data.body?.kind || kind }); setReview(null); invalidate();
    if (data.state === 'completed' || data.state === 'reconciled') { storePending(''); setPending(''); setSelected([]); setText(''); setTitle(''); }
  };
  const confirm = async () => {
    if (!review || busy || pending) return;
    const id = review.planId;
    storePending(id); setPending(id); setBusy(true); setError('');
    try { finish(await commitWorkspaceOperation(id)); }
    catch (e) { setError((e.message || 'Outcome unknown.') + ' Use Check outcome. Do not resend.'); }
    finally { setBusy(false); }
  };
  const check = async () => {
    setBusy(true); setError('');
    try {
      const plan = await getWorkspacePlan(pending);
      if (plan.state === 'review') { setKind(plan.body.kind); setText(plan.body.text || ''); setTitle(plan.body.title || ''); setError('Commit did not start; cancel this review or return to its confirmation.'); setReview({ planId: pending, recipients: plan.recipients, destination: plan.body.destination, kind: plan.body.kind }); }
      else finish(plan);
    } catch (e) { setError(e.message || 'Could not verify outcome. Do not resend.'); }
    finally { setBusy(false); }
  };
  const reconcile = async () => { if (!pending || busy) return; setBusy(true); setError(''); try { finish(await reconcileWorkspacePlan(pending)); } catch (e) { setError(e.message || 'Readback failed. No automatic retry.'); } finally { setBusy(false); } };
  const retryUnstarted = () => { storePending(''); setPending(''); };
  const toggle = id => { setReview(null); setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); };
  const names = { group1: 'Group 1', group2: 'Group 2', both: 'Both' };
  return <section id="workspace-actions" className="mb-5 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
    <h2 className="font-heading font-semibold">{mode === 'announcements' ? 'Group announcement · app inbox' : mode === 'messages' ? 'New private message / selected-student follow-up' : 'Individual & bulk student actions'}</h2>
    <p className="mt-1 text-xs text-slate-500">{batch} / {names[group]} · server-reviewed recipients · no WhatsApp delivery</p>
    {pending && <div role="status" className="mt-3 rounded-lg border border-amber-200 p-3 text-sm text-amber-800">Previous operation: {pending}<div className="mt-2"><button className={cls} onClick={check} disabled={busy}>Check outcome</button>{result?.kind === 'transfer' && ['partial', 'needs_reconciliation'].includes(result.state) && <button className={`${cls} ml-2`} onClick={reconcile} disabled={busy}>Reconcile transfer readback</button>}{review?.planId === pending && <button className={`${cls} ml-2`} onClick={retryUnstarted}>Return to unstarted confirmation</button>}</div><p className="mt-1 text-xs">Partial / unknown transfers require reconciliation. Do not retry a partial bulk operation.</p></div>}
    {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    {result && <div role="status" className="mt-3 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800"><strong>Outcome: {result.state}</strong>{(result.outcomes || []).map(r => <div key={r.studentId} className="mt-1 text-xs">{r.studentId}: {r.state} {r.message || ''}</div>)}</div>}
    <div className="mt-4 space-y-3">
      {mode === 'students' && <label className="block text-xs">Action <select aria-label="Student action" className={`${cls} ml-2`} value={kind} onChange={e => { setKind(e.target.value); setReview(null); }}><option value="message">Private message</option><option value="transfer">Move batch / group</option></select></label>}
      {kind !== 'announcement' && <div className="max-h-44 overflow-auto rounded-lg border border-slate-200 p-3 dark:border-slate-700"><label className="mb-2 block text-xs"><input type="checkbox" checked={students.length > 0 && selected.length === students.length} onChange={e => { setSelected(e.target.checked ? students.map(s => s.id) : []); setReview(null); }} /> Select all current group students</label>{students.map(s => <label key={s.id} className="flex items-center gap-2 py-1 text-xs"><input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggle(s.id)} />{s.name} · {s.id}{!s.membershipConsistent && <span className="text-amber-700">Membership sync needs review</span>}</label>)}</div>}
      {kind === 'announcement' && <fieldset className="rounded-lg border border-slate-200 p-3"><legend className="px-1 text-xs">Target current batch/group workspaces</legend>{batchOptions.map(b => <div key={b} className="mb-2 text-xs"><strong>{b}</strong><div className="mt-1 flex flex-wrap gap-4">{Object.entries(names).map(([key, label]) => { const value = b + '|' + key; return <label key={key}><input type="checkbox" checked={announcementTargets.includes(value)} onChange={e => { setAnnouncementTargets(prev => e.target.checked ? [...prev, value] : prev.filter(v => v !== value)); setReview(null); }} /> {label}</label>; })}</div></div>)}<p className="text-xs text-slate-500">Server deduplicates recipients and rejects empty/non-current workspaces. Maximum 100 recipients per reviewed send.</p></fieldset>}
      {kind === 'transfer' ? <><div className="flex flex-wrap gap-3"><label className="text-xs">Destination batch <select aria-label="Destination batch" className={cls} value={destinationBatch} onChange={e => { setDestinationBatch(e.target.value); setReview(null); }}>{batchOptions.map(b => <option key={b}>{b}</option>)}</select></label><label className="text-xs">Destination group <select aria-label="Destination group" className={cls} value={destinationGroup} onChange={e => { setDestinationGroup(e.target.value); setReview(null); }}>{Object.entries(names).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div><p className="text-xs text-amber-700">Access: destination only. Preserve study history and submitted results. Bulk transfers are per-student, not one atomic transaction. WhatsApp membership is separate.</p></> : <>{kind === 'announcement' && <input aria-label="Announcement title" className={`${cls} w-full`} value={title} onChange={e => { setTitle(e.target.value); setReview(null); }} placeholder="Announcement title" maxLength={200} />}<textarea aria-label="Message text" className={`${cls} w-full`} rows={4} maxLength={4000} value={text} onChange={e => { setText(e.target.value); setReview(null); }} placeholder="Write a message…" /><p className="text-xs text-slate-500">Inbox persists when push fails. A notification does not prove the student has read the message.</p></>}
      <button className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={busy || !!pending} onClick={prepare}>{busy ? 'Checking…' : 'Review recipients & changes'}</button>
    </div>
    {review && <div role="dialog" aria-modal="true" aria-label="Confirm workspace action" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"><div className="max-h-[90vh] w-full max-w-xl overflow-auto rounded-xl bg-white p-6 dark:bg-slate-900"><h3 className="font-semibold">Review {review.kind} · {review.recipients.length} recipient(s)</h3>{review.destination && <p className="mt-2 text-sm text-blue-700">Destination: {review.destination.batch} / {names[review.destination.group]}</p>}<div className="my-4 max-h-64 overflow-auto">{review.recipients.map(s => <div key={s.id} className="border-b border-slate-100 py-2 text-xs">{s.name} · {s.id}<div className="text-slate-500">{s.batch} / {s.group}</div></div>)}</div>{kind !== 'transfer' && <p className="mb-4 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">{title && <strong className="block">{title}</strong>}{text}</p>}<p className="mb-4 text-xs text-amber-700">This is a real operation when deployed. Confirm only after reviewing the exact recipients. No automatic resend.</p><div className="flex justify-end gap-3"><button className={cls} disabled={busy} onClick={() => setReview(null)}>Cancel</button><button className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={busy || !!pending} onClick={confirm}>Confirm {review.kind}</button></div></div></div>}
    {mode === 'announcements' && <div className="mt-6 border-t border-slate-200 pt-4"><h3 className="text-sm font-semibold">Current-group announcements</h3>{announcements.isError && <p role="alert" className="text-xs text-rose-700">{announcements.error.message}</p>}{(announcements.data?.announcements || []).filter(a => (a.workspaceTargets || []).some(t => t.batch === batch && t.group === group)).map(a => <article key={a.id} className="mt-3 rounded-lg border border-slate-200 p-3"><strong className="text-sm">{a.title}</strong><p className="mt-2 whitespace-pre-wrap text-xs text-slate-500">{a.body || a.message}</p></article>)}</div>}
  </section>;
}
