import { useState } from 'react';
import { apiCall } from '@/api/backendClient';

const field = 'rounded border border-slate-300 bg-transparent px-2 py-1 text-sm dark:border-slate-600';
const button = 'rounded bg-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40';

function RequestDecision({ planId, studentId, request, active, refresh }) {
  const [days, setDays] = useState(String(request.requestedDays));
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const decide = async decision => {
    setBusy(true); setError('');
    try {
      await apiCall(`/api/smart-targets/mentor/${encodeURIComponent(planId)}/extension`, {
        method: 'POST', body: { studentId, requestId: request.id, decision, days: decision === 'approved' ? Number(days) : 1, note },
      });
      await refresh();
    } catch (e) { setError(e.message || 'Decision was not saved.'); }
    finally { setBusy(false); }
  };
  return <div className="mt-3 rounded border border-amber-200 p-3">
    <div className="font-semibold">Extension {request.status} · {request.requestedDays} requested day(s)</div>
    <div>{request.reason}</div>
    {request.status === 'pending' && active && <div className="mt-2 flex flex-wrap items-center gap-2">
      <label>Grant days <input aria-label={`Grant days ${studentId}`} type="number" min="1" max="60" value={days} onChange={e => setDays(e.target.value)} className={`${field} w-20`} /></label>
      <input aria-label={`Extension note ${studentId}`} placeholder="Mentor note (optional)" maxLength={300} value={note} onChange={e => setNote(e.target.value)} className={field} />
      <button type="button" className={button} disabled={busy || !Number.isInteger(Number(days)) || Number(days) < 1 || Number(days) > 60} onClick={() => decide('approved')}>Approve</button>
      <button type="button" className={button} disabled={busy} onClick={() => decide('rejected')}>Reject</button>
    </div>}
    {request.status === 'approved' && <div>{request.approvedDays} days granted. {request.note}</div>}
    {request.status === 'rejected' && <div>{request.note}</div>}
    {error && <p role="alert" className="text-rose-600">{error}</p>}
  </div>;
}

export default function SmartTargetFollow({ plan }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true); setError('');
    try { setData(await apiCall(`/api/smart-targets/mentor/${encodeURIComponent(plan.id)}`)); }
    catch (e) { setError(e.message || 'Could not read saved student progress.'); }
    finally { setBusy(false); }
  };
  return <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-700" data-testid="smart-target-follow">
    <p className="text-sm font-semibold">Personal sequence · {plan.includedBackupDays} included backup day(s) · revision budget {plan.revisionBudgetMinutes} min</p>
    <p className="mt-1 text-xs text-slate-500">Each student starts independently. Template edits affect new starters only. Started snapshots and completed work are retained; cancelling makes them read-only. Scores below are labelled by source, not inferred from timer hours.</p>
    <button type="button" className={`${button} mt-3`} disabled={busy} onClick={load}>{busy ? 'Loading…' : data ? 'Refresh Target Follow' : 'Open student Target Follow'}</button>
    {error && <p role="alert" className="mt-2 text-rose-600">{error}</p>}
    {data && <>
      <p className="mt-3 text-sm">{data.started} started · {data.notStarted} not started · {data.fallingBehind} falling behind · {data.pendingRequests} pending extensions · as of {data.today} IST</p>
      <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr>{['Student', 'Personal start / day', 'Progress', 'Delay / backups', 'Extensions', 'Revision due / mastery'].map(t => <th key={t} className="p-2">{t}</th>)}</tr></thead><tbody>
        {data.students.map(s => { const p = s.progress; return <tr key={s.studentId} className="border-t border-slate-200 align-top dark:border-slate-700">
          <td className="p-2">{s.studentId}<br />{s.studentName}{s.membershipReady === false && s.inAudience && <div className="text-amber-700">Enrollment sync required</div>}{!s.inAudience && <div className="text-amber-700">Historical audience</div>}</td>
          <td className="p-2">{p ? <>{p.startDate}<br />{p.complete ? 'Complete' : `Day ${p.currentDay}/${p.totalDays}`}</> : 'Not started'}</td>
          <td className="p-2">{p ? <>{p.completedTasks}/{p.totalTasks} tasks<br />{p.completedDays}/{p.totalDays} days ({p.progressPercent}%)</> : '—'}</td>
          <td className="p-2">{p ? <>{p.overdueDays} day(s) behind<br />{p.backupDaysUsed}/{p.includedBackupDays} used · {p.backupDaysRemaining} left</> : '—'}</td>
          <td className="p-2">{p ? <>{p.approvedExtensionDays} granted · {p.extensionDaysRemaining} left<br />{p.extensionDaysNeeded > 0 ? `${p.extensionDaysNeeded} more needed` : 'Within allowance'}<br />{p.extensions.filter(e => e.status === 'pending').length} pending</> : '—'}</td>
          <td className="p-2">{s.dueRevisions.length} due · {s.chapters.filter(c => c.strength === 'weak').length} weak<br />{s.chapters.length ? `${s.chapters.length} assessed chapter(s)` : 'Not assessed'}</td>
        </tr>; })}
      </tbody></table></div>
      {data.students.filter(s => s.progress || s.chapters.length).map(s => <details key={s.studentId} className="mt-3 rounded border border-slate-200 p-3 text-xs dark:border-slate-700"><summary className="cursor-pointer font-semibold">{s.studentId} · dates, chapters & extension decisions</summary>
        {s.progress && <>
          <p className="mt-2">Deadline {s.progress.deadline} · projected finish {s.progress.projectedFinishDate}. Pending work never auto-completes.</p>
          {s.progress.days.map(d => <div key={d.day} className="mt-1">Day {d.day} · original {d.nominalDate} · scheduled {d.scheduledDate} · projected {d.projectedDate} · {d.done ? `completed ${d.completedOn}` : d.locked ? 'locked' : 'current'}</div>)}
          {s.progress.extensions.map(e => <RequestDecision key={e.id} planId={plan.id} studentId={s.studentId} request={e} active={plan.status === 'active'} refresh={load} />)}
        </>}
        {s.chapters.map(c => <div key={c.revisionKey} className="mt-3 rounded bg-slate-50 p-2 dark:bg-slate-900">{c.subject} · {c.concept} · {c.strength === 'average' ? 'Medium' : c.strength} · mastery {c.accuracy}% · question accuracy {c.questionAccuracy == null ? 'not measured' : `${c.questionAccuracy}% (${c.questionCorrectTotal}/${c.questionAttemptedTotal})`} · next revision {c.dueOn}<br />Latest source: {c.lastAssessmentSource === 'student-reported-question-score' ? 'Student-reported question score (not a verified exam mark)' : 'Written-answer grading'}{c.lastRevisionCompletedAt ? ` · revised ${c.lastRevisionCompletedAt.slice(0, 10)}` : ''}</div>)}
      </details>)}
    </>}
  </div>;
}
