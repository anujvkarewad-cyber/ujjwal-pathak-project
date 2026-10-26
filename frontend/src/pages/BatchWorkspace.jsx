import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { Users, CalendarDays, ClipboardList, Trophy, ArrowUpRight } from 'lucide-react';
import { getMissedTrackerReport } from '@/api/tracker';
import { mergeWorkspaceStudentMetrics, workspaceMetricsWindow } from '@/utils/workspaceStudentMetrics';
import { getWorkspaceRoster } from '@/api/mentorWorkspace';
import WorkspaceActions from '@/components/students/WorkspaceActions';
import Tests from '@/pages/Tests';
import Notes from '@/pages/Notes';
import Messages from '@/pages/Messages';
import PasswordReset from '@/pages/PasswordReset';
import { currentBatchNames, workspaceStudents, WORKSPACE_GROUPS } from '@/utils/batchWorkspace';
import StudentTable from '@/components/students/StudentTable';
import MissedTrackerReport from '@/components/tracker/MissedTrackerReport';
import DailyTracker from '@/pages/DailyTracker';
import Leaderboard from '@/pages/Leaderboard';

const TABS = [
  ['students', 'Students', Users],
  ['grid', 'Daily tracker · Dates', CalendarDays],
  ['daily', 'Daily submissions', ClipboardList],
  ['leaderboard', 'Leaderboard', Trophy],
  ['tests', 'Tests', ClipboardList], ['notes', 'Notes', ClipboardList],
  ['messages', 'Messages', ClipboardList], ['announcements', 'Announcements', ClipboardList],
  ['passwords', 'Password reset', ClipboardList],
];
// Only tools without a scoped workspace tab belong in this secondary directory.
const EXISTING_TOOLS = [
  ['/mcq-scores', 'MCQ scores'], ['/notes-inbox', 'Notes inbox'], ['/workbooks', 'Audit & SM workbooks'],
  ['/daily-targets', 'Daily targets'], ['/target-plans', 'Target plans'], ['/reports', 'Reports'],
];
export default function BatchWorkspace() {
  // Never substitute the legacy mock adapter for the owner's current roster.
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['workspace-roster'], queryFn: getWorkspaceRoster,
  });
  const students = Array.isArray(data?.students) ? data.students : [];
  const batches = currentBatchNames(students);
  const [searchParams] = useSearchParams();
  const focused = students.find(s => s.id === searchParams.get('studentId'));
  const [chosenBatch, setBatch] = useState('');
  const [chosenGroup, setGroup] = useState('');
  const group = chosenGroup || (focused?.groupKey !== 'unknown' && focused?.groupKey) || 'group1';
  const [tab, setTab] = useState('students');
  const [replyDraft, setReplyDraft] = useState(null);
  const metrics = useQuery({
    queryKey: ['workspace-student-metrics', workspaceMetricsWindow()],
    queryFn: () => getMissedTrackerReport({ ...workspaceMetricsWindow(), scope: 'range' }),
    enabled: tab === 'students' && students.length > 0, staleTime: 60000, retry: false,
  });
  const displayStudents = mergeWorkspaceStudentMetrics(students, metrics.data);
  const batch = batches.includes(chosenBatch) ? chosenBatch : focused?.batch || batches[0] || '';
  const groupSpec = WORKSPACE_GROUPS.find(g => g.key === group);
  const rows = workspaceStudents(students, batch, group);
  const mappedCount = WORKSPACE_GROUPS.reduce((n, g) => n + workspaceStudents(students, batch, g.key).length, 0);
  const unassignedCount = students.filter(s => String(s.batch || '').trim() === batch).length - mappedCount;
  const scopeKey = `${batch}:${group}`;

  if (isLoading) return <div role="status" className="p-5 text-slate-500">Loading existing enrollment data…</div>;
  if (error) return <div role="alert" className="rounded-xl border border-rose-200 p-5 text-rose-700">{error.message || 'Current roster could not load.'}<button className="ml-3 underline" onClick={() => refetch()}>Retry</button></div>;
  if (!batch) return <div className="rounded-xl border border-slate-200 p-5">No populated batches found in the current roster. No new batch has been created.</div>;
  return <div className="space-y-5" data-testid="batch-workspace">
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 flex flex-wrap items-center gap-5">
      <label className="text-xs text-slate-500">Batch<select aria-label="Workspace batch" className="ml-3 rounded-lg border border-slate-200 bg-transparent px-3 py-2 text-sm" value={batch} onChange={e => setBatch(e.target.value)}>{batches.map(b => <option key={b}>{b}</option>)}</select></label>
      <div className="flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">{WORKSPACE_GROUPS.map(g => <button key={g.key} aria-pressed={group === g.key} onClick={() => setGroup(g.key)} className={`rounded-md px-4 py-2 text-xs ${group === g.key ? 'bg-white text-blue-600 shadow-sm dark:bg-slate-900' : 'text-slate-500'}`}>{g.label}<span className="ml-2 text-slate-400">{workspaceStudents(students, batch, g.key).length}</span></button>)}</div>
      <span className="text-xs text-slate-500 md:ml-auto">{rows.length} current students · Exclusive membership</span>
    </div>
    {unassignedCount > 0 && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">{unassignedCount} current student(s) have an unknown/unassigned group. They are not assigned automatically. Review them in the original Students page.</p>}
    <nav className="flex gap-5 overflow-x-auto border-b border-slate-200 dark:border-slate-800" aria-label="Group workspace">{TABS.map(([key, label, Icon]) => <button key={key} onClick={() => setTab(key)} className={`flex items-center gap-2 whitespace-nowrap border-b-2 py-3 text-sm ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500'}`}><Icon className="h-4 w-4" />{label}</button>)}</nav>
    <div key={`${scopeKey}:${tab}`}>
      {tab === 'students' && <><WorkspaceActions initialKind={searchParams.get('action')} batch={batch} group={group} students={rows} batches={batches} focusStudentId={focused?.id} mode="students" /><StudentTable providedStudents={workspaceStudents(displayStudents, batch, group)} scopedBatch={batch} scopedGroup={groupSpec.trackerLabel} metricsLoading={metrics.isFetching} metricsError={metrics.error || (metrics.data && (metrics.data.rosterSource !== 'Students Sheet') ? new Error('Complete metric sources unavailable') : null)} onRetryMetrics={metrics.refetch} showMetricsSource /></>}
      {tab === 'grid' && <MissedTrackerReport scopedBatch={batch} scopedGroup={group} />}
      {tab === 'daily' && <DailyTracker providedStudents={students} scopedBatch={batch} scopedGroup={groupSpec.trackerLabel} hideGrid />}
      {tab === 'tests' && <Tests scopedBatch={batch} scopedGroup={groupSpec.trackerLabel} scopedStudentIds={rows.map(s => s.id)} />}
      {tab === 'notes' && <Notes scopedBatch={batch} scopedGroup={groupSpec.trackerLabel} />}
      {tab === 'messages' && <><WorkspaceActions key={replyDraft?.scope === batch + '|' + group ? replyDraft.nonce : 'no-reply'} batch={batch} group={group} students={rows} batches={batches} focusStudentId={replyDraft?.scope === batch + '|' + group ? replyDraft.studentId : focused?.id} initialText={replyDraft?.scope === batch + '|' + group ? replyDraft.text : ''} mode="messages" /><Messages scopedStudentIds={rows.map(s => s.id)} onWorkspaceReply={draft => { setReplyDraft({ ...draft, scope: batch + '|' + group, nonce: Date.now() }); requestAnimationFrame(() => document.getElementById('workspace-actions')?.scrollIntoView({ behavior: 'smooth' })); }} /></>}
      {tab === 'announcements' && <WorkspaceActions initialKind={searchParams.get('action')} batch={batch} group={group} students={rows} batches={batches} focusStudentId={focused?.id} mode="announcements" />}
      {tab === 'passwords' && <PasswordReset scopedStudentIds={rows.map(s => s.id)} />}
      {tab === 'leaderboard' && <Leaderboard scopedBatch={batch} scopedGroup={groupSpec.trackerLabel} />}
    </div>
    <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <details><summary className="cursor-pointer font-heading font-semibold">Other mentor tools · global</summary>
      <p className="mt-1 text-xs text-slate-500">Original global pages remain available. Workspace tabs above carry the selected cohort; the global links below do not. Check audience before any write.</p>
      <div className="mt-4 flex flex-wrap gap-3">{EXISTING_TOOLS.map(([to, label]) => <Link key={to} to={to} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs text-blue-600 dark:border-slate-700">{label}<ArrowUpRight className="h-3 w-3" /></Link>)}</div>
      </details>
      <p className="mt-4 text-xs text-amber-700">Every transfer/message/announcement requires a server recipient review and explicit confirmation. No automatic retry after an uncertain outcome. Transfer materials access is destination-only; history is preserved.</p>
    </section>
  </div>;
}
