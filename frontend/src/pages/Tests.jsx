// Tests — mentor view of every student's mentor-test attempts.
// MCQ tests arrive auto-graded; paper tests carry the marks the student
// wrote himself after checking the answer key + marking scheme.
import { useEffect, useMemo, useState } from 'react';
import { ClipboardCheck, FileSearch, PenLine, Search, Timer } from 'lucide-react';
import { fetchTestHistory } from '@/api/tests';
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

export default function Tests() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  useEffect(() => {
    let alive = true;
    fetchTestHistory()
      .then((res) => { if (alive) setEntries(res?.entries || []); })
      .catch((e) => { if (alive) setError(e?.message || 'Could not load test records'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (filter !== 'all' && e.kind !== filter) return false;
      if (!q) return true;
      return [e.studentId, e.studentName, e.title, e.subject, e.batch]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q));
    });
  }, [entries, filter, query]);

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

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
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
        <div className="relative ml-auto">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search student, test, batch…"
            className="pl-9 pr-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
          />
        </div>
      </div>

      {/* Table */}
      <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900">
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
                      <div className="text-xs text-slate-400">{e.studentId}{e.batch ? ` · ${e.batch}` : ''}</div>
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
