import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Users,
  Activity,
  ListChecks,
  Award,
  Search,
  AlertTriangle,
  RefreshCw,
  Table2,
} from 'lucide-react';
import KPICard from '@/components/dashboard/KPICard';
import { CardSkeleton, Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';
import { getMcqScores } from '@/api/mcqScores';

const RANGES = [
  { key: '7', label: '7 din' },
  { key: '30', label: '30 din' },
  { key: '90', label: '90 din' },
  { key: 'all', label: 'Poora' },
];

const fmtPct = (v) => (Number.isFinite(Number(v)) ? `${Number(v).toFixed(1)}%` : '—');

const fmtDate = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};

export default function McqScores() {
  const [range, setRange] = useState('30');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const body = await getMcqScores({ range, q: debounced });
      setData(body);
    } catch (err) {
      setError(err?.message || 'Could not load MCQ scores.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [range, debounced]);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(() => data?.stats || {}, [data]);
  const students = useMemo(() => data?.students || [], [data]);

  return (
    <div className="space-y-6" data-testid="mcq-scores-page">
      <header>
        <h1 className="font-heading text-2xl font-bold text-slate-900 dark:text-white">
          MCQ Scores
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Students ke Daily set aur Practice sets ke auto-graded marks — question-wise detail ke
          saath.
        </p>
      </header>

      {/* stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} height="h-28" />)
        ) : (
          <>
            <KPICard icon={Users} label="Students" value={stats.students ?? 0} tone="blue" testid="mcq-stat-students" />
            <KPICard icon={Activity} label="Attempts" value={stats.attempts ?? 0} tone="emerald" testid="mcq-stat-attempts" />
            <KPICard icon={ListChecks} label="Questions Solved" value={stats.questionsSolved ?? 0} tone="violet" testid="mcq-stat-questions" />
            <KPICard
              icon={Award}
              label="Cohort Average"
              value={stats.cohortAverage == null ? '—' : Number(stats.cohortAverage).toFixed(1)}
              suffix={stats.cohortAverage == null ? '' : '%'}
              tone="amber"
              testid="mcq-stat-average"
            />
          </>
        )}
      </div>

      {/* controls */}
      <div className="flex flex-col md:flex-row md:items-center gap-3 justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setRange(r.key)}
              data-testid={`mcq-range-${r.key}`}
              className={cn(
                'px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-colors',
                range === r.key
                  ? 'bg-[#2563EB] text-white border-[#2563EB]'
                  : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-slate-300',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="relative md:w-72">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Student, ID ya batch…"
            data-testid="mcq-search"
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
          />
        </div>
      </div>

      {/* error */}
      {error && (
        <div
          data-testid="mcq-error"
          className="flex items-center gap-3 rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300"
        >
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            className="flex items-center gap-1.5 font-semibold hover:underline"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      )}

      {/* table */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="mcq-table">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
                <th className="px-5 py-3 font-semibold">Student</th>
                <th className="px-5 py-3 font-semibold text-right">Attempts</th>
                <th className="px-5 py-3 font-semibold text-right">Marks</th>
                <th className="px-5 py-3 font-semibold text-right">Average</th>
                <th className="px-5 py-3 font-semibold text-right">Best</th>
                <th className="px-5 py-3 font-semibold text-right">Last Attempt</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-100 dark:border-slate-800/60">
                    {Array.from({ length: 6 }).map((__, j) => (
                      <td key={j} className="px-5 py-4">
                        <Skeleton className="h-4 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : students.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-14 text-center">
                    <Table2 className="w-8 h-8 mx-auto text-slate-300 dark:text-slate-600 mb-3" />
                    <div className="text-sm text-slate-500 dark:text-slate-400">
                      No student MCQ attempts have synced yet. Marks will appear here once students
                      solve Daily sets or Practice in the app.
                    </div>
                  </td>
                </tr>
              ) : (
                students.map((row) => (
                  <tr
                    key={row.studentId}
                    data-testid={`mcq-row-${row.studentId}`}
                    className="border-b border-slate-100 dark:border-slate-800/60 last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                  >
                    <td className="px-5 py-3.5">
                      <div className="font-medium text-slate-900 dark:text-white">
                        <Link
                          to={`/students/${row.studentId}`}
                          title={`Open ${row.name}'s full profile`}
                          className="hover:text-[#2563EB] dark:hover:text-blue-300 underline-offset-2 hover:underline"
                          data-testid={`mcq-profile-${row.studentId}`}
                        >
                          {row.name}
                        </Link>
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {row.studentId}
                        {row.batch ? ` · ${row.batch}` : ''}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-right text-slate-700 dark:text-slate-200">{row.attempts}</td>
                    <td className="px-5 py-3.5 text-right text-slate-700 dark:text-slate-200">
                      {row.marks}
                      <span className="text-slate-400 dark:text-slate-500">/{row.questionsSolved}</span>
                    </td>
                    <td className="px-5 py-3.5 text-right font-semibold text-[#2563EB] dark:text-blue-400">
                      {fmtPct(row.average)}
                    </td>
                    <td className="px-5 py-3.5 text-right font-semibold text-emerald-600 dark:text-emerald-400">
                      {fmtPct(row.best)}
                    </td>
                    <td className="px-5 py-3.5 text-right text-slate-600 dark:text-slate-300">
                      {fmtDate(row.lastAttempt)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
