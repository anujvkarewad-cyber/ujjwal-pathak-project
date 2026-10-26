// Tests — mentor view of every student's mentor-test attempts.
// MCQ tests arrive auto-graded; paper tests carry the marks the student
// wrote himself after checking the answer key + marking scheme.
import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ChevronDown, ClipboardCheck, FileSearch, PenLine, Search, ShieldAlert, Timer, Users } from 'lucide-react';
import { fetchTestHistory, fetchTestHistoryGroups, notifyMissingSubmissions } from '@/api/tests';
import TestAuthoring from '@/components/tests/TestAuthoring';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const fmtDate = (iso) => {
  try {
    return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
};

const FILTERS = [
  { key: 'all', label: 'All tests' },
  { key: 'mcq-test', label: 'MCQ tests' },
  { key: 'paper-test', label: 'Paper tests' },
];

// A student's group is shown EXACTLY as the Students sheet writes it - "Group 1",
// "Group 2" or "Both". It is never expanded into "Group 1 + Group 2": that made a
// Group-2 test look like it also contained Group-1 students (owner, 17-Oct-2026).
const groupOf = (r) => (r?.groupText || (r?.groups || []).filter(Boolean).join(' + ')).trim();

// Batch tells who is in the program, the group cell tells which class they sit in.
const whoLabel = (r) => [r?.batch, groupOf(r)].filter(Boolean).join(' · ') || '—';

// The audience chip repeats the test's own wording, so it can never disagree with the
// upload form. Empty means the test was published to the whole batch.
const scopeLabel = (raw) => String(raw || '').trim() || 'All groups';

function RosterRow({ who, tone, right, hint }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 border-b border-slate-100 dark:border-slate-800/60 last:border-0">
      <div className="min-w-0">
        <div className={cn('text-sm font-semibold truncate', tone === 'miss' ? 'text-slate-500 dark:text-slate-400' : 'text-slate-800 dark:text-slate-100')}>
          {who.studentName || who.studentId}
        </div>
        <div className="text-[11px] text-slate-400 truncate">
          {who.studentId} · {whoLabel(who)}
          {groupOf(who) ? (
            <span className={cn('ml-1 font-semibold', tone === 'miss' ? 'text-amber-600 dark:text-amber-400' : 'text-[#2563EB]')}>[{groupOf(who)}]</span>
          ) : (
            <span className="ml-1 font-semibold text-slate-400">{hint || '[no group set]'}</span>
          )}
        </div>
      </div>
      {right ? <div className="text-xs text-slate-500 whitespace-nowrap text-right shrink-0">{right}</div> : null}
    </div>
  );
}

function GroupCard({ g, open, onToggle, degraded, scoped = false }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [status, setStatus] = useState('');
  const pending = g.notSubmitted?.length || 0;

  const onNotify = async () => {
    if (busy || scoped) { if (scoped) setStatus('Use workspace private messages to follow up only selected cohort students.'); return; }
    setBusy(true);
    setStatus('');
    try {
      const res = await notifyMissingSubmissions(g.key, note.trim());
      const skipped = (res?.noDevice || []).length;
      setStatus(`Pushed to ${res?.sent || 0}/${(g.notSubmitted || []).length}${skipped ? ` · ${skipped} with no registered device` : ''}`);
    } catch (e) {
      setStatus(e?.message || 'Could not send');
    } finally {
      setBusy(false);
    }
  };
  const scope = g.knownAudience ? scopeLabel(g.audienceGroup) : '';
  return (
    <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 overflow-hidden">
      <button type="button" onClick={onToggle} data-testid={`test-group-${g.key}`}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/40">
        <ChevronDown className={cn('w-4 h-4 text-slate-400 shrink-0 transition-transform', open ? '' : '-rotate-90')} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-800 dark:text-slate-100 truncate">{g.title}</span>
            {g.kind === 'paper-test'
              ? <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">Paper</span>
              : <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">MCQ</span>}
            {g.batch ? (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{g.batch}</span>
            ) : null}
            {scope ? (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{scope}</span>
            ) : null}
            {degraded ? (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">sheet not read</span>
            ) : null}
            {g.audienceGroupUnreadable ? (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                title={`The test says group "${g.audienceGroup}", which is not one of Group 1 / Group 2 / Both on the Students sheet, so the whole batch is listed.`}>
                group not recognised
              </span>
            ) : null}
          </div>
          <div className="text-[11px] text-slate-400 mt-0.5 truncate">
            {[g.subject, g.testDate, g.batch].filter(Boolean).join(' · ')}
            {g.knownAudience ? ` · ${g.totalStudents} of ${g.audienceSize} submitted` : ''}
            {g.unknownScope?.length ? ` · ${g.unknownScope.length} unverified` : ''}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {g.knownAudience ? (
            pending
              ? <span className="px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">{pending} did not submit</span>
              : <span className="px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">everyone in</span>
          ) : (
            <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">audience unknown</span>
          )}
          <span className="text-sm font-bold text-slate-700 dark:text-slate-200 whitespace-nowrap">
            {g.totalStudents}{g.knownAudience ? `/${g.audienceSize}` : ''}
          </span>
        </div>
      </button>

      {open ? (
        <div className="px-4 pb-4 grid md:grid-cols-2 gap-4">
          <div className="md:col-span-2 text-[11px] text-slate-400 leading-snug">
            Roster = the students the Students sheet puts in
            {g.batch ? <b> {g.batch}</b> : ' every batch'}
            {g.audienceGroup ? <b> · {g.audienceGroup}</b> : ' · all groups'}
            . A <b>Both</b> student is their own group on the sheet, so they appear only in a Both Groups test —
            never inside a single-group test, and never written as &#8220;Group 1 + Group 2&#8221;.
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Submitted · {g.submitted.length}
            </div>
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-1">
              {g.submitted.length === 0 ? (
                <div className="py-3 text-xs text-slate-400">Nobody has submitted this test yet.</div>
              ) : g.submitted.map((s) => (
                <RosterRow key={s.studentId} who={s} right={(
                  <div>
                    {s.score == null
                      ? <span className="text-amber-600 dark:text-amber-400 font-semibold">marks due</span>
                      : (
                        <span className="font-bold text-slate-800 dark:text-slate-100">
                          {s.score}{s.total ? `/${s.total}` : ''}
                          {s.scorePct != null ? <span className={cn('ml-1.5 font-bold', s.scorePct >= 60 ? 'text-emerald-600' : 'text-amber-600')}>{s.scorePct}%</span> : null}
                        </span>
                      )}
                    <div className="text-[11px] text-slate-400 font-normal">
                      {fmtDate(s.lastAt)}{s.attempts > 1 ? ` · ${s.attempts} attempts` : ''}{s.selfMarks ? ' · self marks' : ''}
                    </div>
                  </div>
                )} />
              ))}
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-semibold text-slate-500 mb-1">
              <Users className="w-3.5 h-3.5 text-amber-500" /> Still missing · {pending}
            </div>
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-1">
              {!g.knownAudience ? (
                <div className="py-3 text-xs text-slate-400">This record has no test on file, so the audience cannot be worked out — only attempts are listed.</div>
              ) : pending === 0 ? (
                <div className="py-3 text-xs text-emerald-600 dark:text-emerald-400 font-semibold">Everyone in the audience has submitted. 🎉</div>
              ) : g.notSubmitted.map((s) => <RosterRow key={s.studentId} who={s} tone="miss" right={<span className="text-amber-600 dark:text-amber-400 font-semibold">not submitted</span>} />)}
            </div>
            {g.knownAudience && pending > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  data-testid={`notify-${g.key}`}
                  disabled={busy}
                  onClick={onNotify}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#2563EB] text-white hover:bg-[#1d4ed8] disabled:opacity-60"
                >
                  {busy ? 'Sending…' : `Push these ${pending} student${pending > 1 ? 's' : ''}`}
                </button>
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Optional wording (blank = default reminder)"
                  className="flex-1 min-w-[180px] px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
                />
                {status ? <span className="text-[11px] text-slate-500">{status}</span> : null}
              </div>
            ) : null}
            {g.unknownScope?.length ? (
              <div className="mt-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 px-3 py-2">
                <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-semibold text-slate-500">
                  <FileSearch className="w-3.5 h-3.5" /> Group not set in the sheet · {g.unknownScope.length}
                </div>
                <div className="mt-1 text-[11px] text-slate-500 leading-snug">
                  This test was aimed at <b>{scopeLabel(g.audienceGroup)}</b>, and the Students sheet does not say which
                  group these students sit in, so we cannot tell whether it was for them. They are <b>not</b> listed as missing and the push
                  button will not reach them — set their Group cell in the sheet, then refresh.
                </div>
                <div className="mt-1 divide-y divide-slate-100 dark:divide-slate-800/60">
                  {g.unknownScope.map((s) => (
                    <div key={s.studentId} className="py-1 text-xs text-slate-500">
                      <span className="font-semibold text-slate-600 dark:text-slate-300">{s.studentName || s.studentId}</span>
                      <span className="text-slate-400"> · {s.studentId}</span>
                      {s.batch ? <span className="text-slate-400"> · {s.batch}</span> : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {g.noAccess?.length ? (
              <div className="mt-2 flex items-start gap-1.5 text-[11px] text-slate-400">
                <ShieldAlert className="w-3.5 h-3.5 mt-px text-slate-400 shrink-0" />
                {g.noAccess.length} student{g.noAccess.length > 1 ? 's' : ''} in this audience {g.noAccess.length > 1 ? 'have' : 'has'} app access switched off, so they are not counted as missing ({g.noAccess.join(', ')}).
              </div>
            ) : null}
          </div>
          {g.outsideAudience?.length ? (
            <div className="md:col-span-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 px-3 py-2" data-testid={`outside-${g.key}`}>
              <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-semibold text-slate-500">
                <FileSearch className="w-3.5 h-3.5" /> Submitted, but not in this roster · {g.outsideAudience.length}
              </div>
              <div className="mt-1 text-[11px] text-slate-500 leading-snug">
                The Students sheet puts these students in a different group or batch than this test was published for,
                so they are not counted in the {g.audienceSize} above. Their marks are kept — they are listed here so
                nothing disappears.
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                {g.outsideAudience.map((s) => (
                  <span key={s.studentId} className="text-[11px] text-slate-500">
                    <b className="text-slate-600 dark:text-slate-300">{s.studentName || s.studentId}</b>
                    {s.groupText ? ` [${s.groupText}]` : ''}
                    {s.scorePct != null ? ` · ${s.scorePct}%` : (s.score == null ? ' · marks due' : ` · ${s.score}`)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Submissions({ scopedStudentIds } = {}) {
  const [entries, setEntries] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('byTest');   // 'byTest' | 'flat'
  const [onlyPending, setOnlyPending] = useState(false);
  const [openKey, setOpenKey] = useState(null);
  const [scope, setScope] = useState({ source: 'sheet', note: '' });

  useEffect(() => {
    let alive = true;
    Promise.allSettled([fetchTestHistory(), fetchTestHistoryGroups()]).then(([flat, grouped]) => {
      if (!alive) return;
      if (flat.status === 'fulfilled') setEntries((flat.value?.entries || []).filter(e => !scopedStudentIds || scopedStudentIds.includes(e.studentId)));
      else setError(flat.reason?.message || 'Could not load test records');
      if (grouped.status === 'fulfilled' && Array.isArray(grouped.value?.groups)) {
        setGroups(grouped.value.groups.map(g => scopedStudentIds ? ({ ...g, submitted: (g.submitted || []).filter(s => scopedStudentIds.includes(s.studentId)), notSubmitted: (g.notSubmitted || []).filter(s => scopedStudentIds.includes(s.studentId)), unknownScope: [] }) : g).filter(g => !scopedStudentIds || g.submitted.length || g.notSubmitted.length));
        setScope({ source: grouped.value.scopeSource || 'sheet', note: grouped.value.scopeNote || '' });
      } else {
        // Grouping needs the /test-history/groups endpoint. On a backend that predates
        // it, do not show an empty "by test" tab - fall back to the flat list.
        setMode('flat');
      }
      setLoading(false);
    });
    return () => { alive = false; };
  }, [scopedStudentIds]);

  // The flat list comes from the raw attempt feed, which has no group field - borrow
  // the labels from the grouped payload so both views say the same thing.
  const groupsBySid = useMemo(() => {
    const m = {};
    groups.forEach((g) => {
      [...(g.submitted || []), ...(g.notSubmitted || [])].forEach((r) => {
        if (r?.studentId && !m[r.studentId]) m[r.studentId] = groupOf(r) ? [groupOf(r)] : [];
      });
    });
    return m;
  }, [groups]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (filter !== 'all' && e.kind !== filter) return false;
      if (!q) return true;
      return [e.studentId, e.studentName, e.title, e.subject, e.batch, ...(groupsBySid[e.studentId] || [])]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [entries, filter, query, groupsBySid]);

  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groups.filter((g) => {
      if (filter === 'mcq-test' && g.kind !== 'mcq-test') return false;
      if (filter === 'paper-test' && g.kind !== 'paper-test') return false;
      if (onlyPending && !(g.notSubmitted || []).length) return false;
      if (!q) return true;
      const hay = [g.title, g.subject, g.batch, g.audienceGroup, ...(g.groupLabels || [])]
        .concat(g.submitted.map((s) => [s.studentId, s.studentName, s.groupText]))
        .concat(g.notSubmitted.map((s) => [s.studentId, s.studentName, s.groupText]))
        .concat((g.unknownScope || []).map((s) => [s.studentId, s.studentName]))
        .flat().filter(Boolean).map((v) => String(v).toLowerCase());
      return hay.some((v) => v.includes(q));
    });
  }, [groups, filter, onlyPending, query]);

  const pendingTotal = useMemo(() => groups.reduce((a, g) => a + (g.notSubmitted?.length || 0), 0), [groups]);

  const stats = useMemo(() => {
    const students = new Set(entries.map((e) => e.studentId));
    const pending = entries.filter((e) => e.kind === 'paper-test' && e.score == null).length;
    const mcq = entries.filter((e) => e.kind === 'mcq-test' && e.scorePct != null);
    const avg = mcq.length ? Math.round(mcq.reduce((a, e) => a + e.scorePct, 0) / mcq.length) : null;
    return { total: entries.length, students: students.size, pending, avg };
  }, [entries]);

  return (
    <div className="space-y-5">
      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 p-4">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold uppercase tracking-wide"><ClipboardCheck className="w-4 h-4 text-[#2563EB]" /> Submissions</div>
          <div className="text-2xl font-bold mt-1 text-slate-900 dark:text-white">{loading ? '—' : stats.total}</div>
        </div>
        <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 p-4">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold uppercase tracking-wide"><Timer className="w-4 h-4 text-emerald-600" /> Students tested</div>
          <div className="text-2xl font-bold mt-1 text-slate-900 dark:text-white">{loading ? '—' : stats.students}</div>
        </div>
        <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 p-4">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold uppercase tracking-wide"><PenLine className="w-4 h-4 text-amber-500" /> Marks due</div>
          <div className="text-2xl font-bold mt-1 text-slate-900 dark:text-white">{loading ? '—' : stats.pending}</div>
          <div className="text-[11px] text-slate-400 mt-0.5">paper tests awaiting self marks</div>
        </div>
        <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 p-4">
          <div className="flex items-center gap-2 text-slate-500 text-xs font-semibold uppercase tracking-wide"><FileSearch className="w-4 h-4 text-violet-500" /> Avg MCQ score</div>
          <div className="text-2xl font-bold mt-1 text-slate-900 dark:text-white">{loading ? '—' : stats.avg == null ? '—' : `${stats.avg}%`}</div>
        </div>
      </div>

      {/* View + filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
          {[{ key: 'byTest', label: 'By test' }, { key: 'flat', label: 'Flat list' }].map((m) => (
            <button
              key={m.key}
              type="button"
              data-testid={`mode-${m.key}`}
              onClick={() => setMode(m.key)}
              className={cn(
                'px-3 py-1.5 text-xs font-semibold transition-colors',
                mode === m.key
                  ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/60',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors',
              filter === f.key
                ? 'bg-[#2563EB] text-white border-[#2563EB]'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-[#2563EB]',
            )}
          >
            {f.label}
          </button>
        ))}
        {mode === 'byTest' && groups.length > 0 ? (
          <button
            type="button"
            onClick={() => setOnlyPending((v) => !v)}
            data-testid="filter-only-pending"
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors',
              onlyPending
                ? 'bg-amber-500 text-white border-amber-500'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-amber-500',
            )}
          >
            {pendingTotal} still missing{onlyPending ? ' · showing pending tests only' : ''}
          </button>
        ) : null}
        <div className="relative ml-auto">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search student, test, batch, group…"
            className="pl-9 pr-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
          />
        </div>
      </div>

      {mode === 'byTest' ? (
        <div className="space-y-2.5">
          {!loading && scope.source !== 'sheet' ? (
            <div className="flex items-start gap-2 rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50/70 dark:bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
              <ShieldAlert className="w-3.5 h-3.5 mt-px shrink-0" />
              <span>{scope.note || 'The Students sheet could not be read, so batch and group below come from the app’s own records.'}</span>
            </div>
          ) : null}
          {loading && Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 bg-white dark:bg-slate-900">
              <Skeleton className="h-5 w-52" />
            </div>
          ))}
          {!loading && visibleGroups.length === 0 ? (
            <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 px-4 py-10 text-center text-sm text-slate-500">
              {groups.length === 0
                ? 'No test submissions yet. Publish a test (or wait for students to sync their attempts) and every test will appear here with its two rosters — who submitted, who still owes one.'
                : 'No test matches this filter.'}
            </div>
          ) : (
            visibleGroups.map((g) => (
              <GroupCard
                key={g.key}
                g={g}
                open={openKey === g.key}
                scoped={!!scopedStudentIds}
                degraded={scope.source !== 'sheet'}
                onToggle={() => setOpenKey((k) => (k === g.key ? null : g.key))}
              />
            ))
          )}
        </div>
      ) : null}

      {/* Table (flat list) */}
      <div className={cn('border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900', mode === 'byTest' && 'hidden')}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60">
                <th className="px-4 py-3 font-semibold">Student</th>
                <th className="px-4 py-3 font-semibold">Test</th>
                <th className="px-4 py-3 font-semibold">Type</th>
                <th className="px-4 py-3 font-semibold">Marks</th>
                <th className="px-4 py-3 font-semibold">Submitted</th>
              </tr>
            </thead>
            <tbody>
              {loading && Array.from({ length: 4 }).map((_, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-slate-800/60">
                  <td colSpan={5} className="px-4 py-3"><Skeleton className="h-6 w-full" /></td>
                </tr>
              ))}
              {!loading && filtered.map((e) => {
                const pct = e.total ? Math.round((e.score / e.total) * 100) : null;
                const good = pct != null && pct >= 60;
                return (
                  <tr key={`${e.studentId}-${e.entryId || e.id}`} className="border-b border-slate-100 dark:border-slate-800/60 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-800 dark:text-slate-100">{e.studentName || e.studentId}</div>
                      <div className="text-xs text-slate-400">
                        {e.studentId} · {whoLabel({ batch: e.batch, groupText: groupOf({ groupText: e.groupText, groups: groupsBySid[e.studentId] }) })}
                        {groupOf({ groupText: e.groupText, groups: groupsBySid[e.studentId] }) ? (
                          <span className="ml-1 font-semibold text-[#2563EB]">[{groupOf({ groupText: e.groupText, groups: groupsBySid[e.studentId] })}]</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-700 dark:text-slate-200">{e.title}</div>
                      {e.subject ? <div className="text-xs text-slate-400">{e.subject}</div> : null}
                    </td>
                    <td className="px-4 py-3">
                      {e.kind === 'paper-test' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">Paper</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">MCQ</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {e.score == null ? (
                        <span className="text-xs font-semibold text-amber-600 dark:text-amber-400">marks due</span>
                      ) : (
                        <div>
                          <span className="font-bold text-slate-800 dark:text-slate-100">{e.score}{e.total ? `/${e.total}` : ''}</span>
                          {pct != null ? <span className={cn('ml-2 text-xs font-bold', good ? 'text-emerald-600' : 'text-amber-600')}>{pct}%</span> : null}
                          {e.kind === 'paper-test' && e.selfMarks ? (
                            <div className="text-[11px] text-violet-600 dark:text-violet-400 font-medium mt-0.5">self-evaluated by student</div>
                          ) : null}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fmtDate(e.at)}</td>
                  </tr>
                );
              })}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-500">
                    {entries.length === 0
                      ? 'No test submissions yet. When students give mentor tests in the app, every attempt — MCQ scores and paper self-evaluation marks — appears here.'
                      : 'No records match this filter.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {error ? (
        <div className="border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-500/5 rounded-lg px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
          {error} — make sure the mentor backend is running.
        </div>
      ) : null}
    </div>
  );
}

const TABS = [
  { key: 'authoring', label: 'My tests' },
  { key: 'submissions', label: 'Student submissions' },
];

export default function Tests({ scopedBatch, scopedGroup, scopedStudentIds } = {}) {
  const [tab, setTab] = useState('authoring');

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            data-testid={`tab-${t.key}`}
            className={cn(
              'px-3.5 py-2 rounded-lg text-sm font-semibold border transition-colors',
              tab === t.key
                ? 'bg-[#2563EB] text-white border-[#2563EB]'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-[#2563EB]',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'authoring' ? (
        <TestAuthoring scopedBatch={scopedBatch} scopedGroup={scopedGroup} />
      ) : (
        <div className="space-y-5">
          <p className="text-xs text-slate-400">
            Every attempt students make in the app — MCQ scores and paper-test self marks — appears below.
          </p>
          <Submissions scopedStudentIds={scopedStudentIds} />
        </div>
      )}
    </div>
  );
}
