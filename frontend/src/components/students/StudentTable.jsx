import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, ChevronLeft, ChevronRight, Eye } from 'lucide-react';
import { RiskBadge, StatusBadge } from '@/components/common/RiskBadge';
import { Skeleton } from '@/components/common/Skeleton';
import { useStudents } from '@/api/hooks';
import { ALL_BATCHES } from '@/constants/batches';
import { matchesStudentGroup } from '@/utils/studentGroup';
import { cn } from '@/utils/format';

const PAGE_SIZE = 8;

function FilterSelect({ value, onChange, options, testid, disabled = false }) {
  return (
    <select
      data-testid={testid}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 px-3 pr-8 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export default function StudentTable({ scopedBatch, scopedGroup, providedStudents, metricsLoading = false, metricsError, onRetryMetrics, showMetricsSource = false } = {}) {
  const { data, isLoading } = useStudents({ enabled: !providedStudents });
  const all = providedStudents || data?.students;
  const options = useMemo(() => providedStudents ? { attemptOptions: ['All Attempts'], statusOptions: ['All Status', ...new Set(providedStudents.map(s => s.status).filter(Boolean))] } : data?.options, [providedStudents, data?.options]);
  const batchOptions = useMemo(() => {
    const actual = (all || []).map((student) => student.batch).filter(Boolean);
    const supplied = (options?.batchOptions || []).filter((value) => value && value !== ALL_BATCHES);
    return [ALL_BATCHES, ...new Set([...actual, ...supplied])];
  }, [all, options]);

  const [q, setQ] = useState('');
  const [batch, setBatch] = useState(scopedBatch || 'All Batches');
  const [attempt, setAttempt] = useState('All Attempts');
  const [group, setGroup] = useState(scopedGroup || 'All Groups');
  const [status, setStatus] = useState('All Status');
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const src = all || [];
    return src.filter(s => {
      if (q && !`${s.name} ${s.id} ${s.email}`.toLowerCase().includes(q.toLowerCase())) return false;
      if (batch !== 'All Batches' && s.batch !== batch) return false;
      if (attempt !== 'All Attempts' && s.attempt !== attempt) return false;
      if (!matchesStudentGroup(s.group, group)) return false;
      if (status !== 'All Status' && s.status !== status) return false;
      return true;
    });
  }, [all, q, batch, attempt, group, status]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const rows = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const wrap = (fn) => (v) => { fn(v); setPage(1); };

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden" data-testid="student-table">
      {showMetricsSource && <div className="border-b border-slate-200 px-5 py-3 text-xs text-slate-500 dark:border-slate-800" role="status">Attendance: last 5 completed IST days from Daily Tracker; excused days excluded. Original risk bands: below 70% At Risk, 70–79% Watch, 80%+ Healthy. No ranking or account changes.{metricsLoading && ' Refreshing metrics…'}{metricsError && <p role="alert" className="mt-2 text-amber-700">Metrics could not load. Enrollment is still shown; missing data is not absence.{onRetryMetrics && <button className="ml-2 underline" onClick={() => onRetryMetrics()}>Retry metrics</button>}</p>}</div>}
      <div className="p-5 border-b border-slate-200 dark:border-slate-800 space-y-3">
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          <div className="flex items-center gap-2 h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400" />
            <input
              data-testid="student-search"
              value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }}
              placeholder="Search by name, id, email..."
              className="bg-transparent outline-none text-sm w-full text-slate-700 dark:text-slate-200 placeholder:text-slate-400"
            />
          </div>
          <span className="text-xs text-slate-500 dark:text-slate-400 md:ml-auto" data-testid="student-count">
            Showing <span className="font-semibold text-slate-700 dark:text-slate-200">{filtered.length}</span> students
          </span>
        </div>
        {options && (
          <div className="flex flex-wrap gap-2">
            <FilterSelect disabled={!!scopedBatch} value={batch} onChange={wrap(setBatch)} options={batchOptions} testid="filter-batch" />
            <FilterSelect value={attempt} onChange={wrap(setAttempt)} options={options.attemptOptions} testid="filter-attempt" />
            <FilterSelect disabled={!!scopedGroup} value={group} onChange={wrap(setGroup)} options={['All Groups', 'Group 1', 'Group 2', 'Both Groups']} testid="filter-group" />
            <FilterSelect value={status} onChange={wrap(setStatus)} options={options.statusOptions} testid="filter-status" />
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
              <th className="px-5 py-3">Student</th>
              <th className="px-5 py-3">Batch</th>
              <th className="px-5 py-3">Group</th>
              <th className="px-5 py-3">Attendance</th>
              <th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Risk</th>
              <th className="px-5 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 5 }).map((_, i) => (
              <tr key={i} className="border-b border-slate-100 dark:border-slate-800">
                <td className="px-5 py-3" colSpan={7}><Skeleton className="h-8 w-full" /></td>
              </tr>
            ))}
            {!isLoading && rows.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors" data-testid={`row-${s.id}`}>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <span className="grid h-9 w-9 place-items-center rounded-full bg-blue-50 text-xs text-blue-600">{String(s.name || s.id).split(' ').map(x => x[0]).slice(0, 2).join('')}</span>
                    <div>
                      <div className="font-semibold text-slate-900 dark:text-white">{s.name}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">{s.id}{s.level ? ` · ${s.level}` : ''}</div>
                    </div>
                  </div>
                </td>
                <td className="px-5 py-3 text-slate-700 dark:text-slate-300">{s.batch}</td>
                <td className="px-5 py-3 text-slate-700 dark:text-slate-300">{s.group}</td>
                <td className="px-5 py-3">
                  {s.attendance == null ? <span title={s.metricsReason || 'Attendance unavailable'} className="text-xs text-slate-400">{metricsLoading ? 'Loading…' : 'Unavailable'}</span> : <div className="flex items-center gap-2 min-w-[100px]">
                    <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                      <div className={cn('h-full rounded-full', s.attendance >= 80 ? 'bg-emerald-500' : s.attendance >= 70 ? 'bg-amber-500' : 'bg-rose-500')} style={{ width: `${s.attendance}%` }} />
                    </div>
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 w-8 text-right">{s.attendance}%</span>
                  </div>}
                </td>
                <td className="px-5 py-3">{s.status ? <StatusBadge status={s.status} /> : <span className="text-xs text-slate-400">—</span>}</td>
                <td className="px-5 py-3">{s.risk ? <RiskBadge risk={s.risk} /> : <span className="text-xs text-slate-400">Not assessed</span>}</td>
                <td className="px-5 py-3 text-right">
                  <Link to={`/students/${s.id}`} data-testid={`view-${s.id}`} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium text-[#2563EB] hover:bg-blue-50 dark:hover:bg-blue-500/10 transition-colors">
                    <Eye className="w-3.5 h-3.5" /> View
                  </Link>
                </td>
              </tr>
            ))}
            {!isLoading && rows.length === 0 && (
              <tr><td colSpan={7} className="px-5 py-16 text-center text-sm text-slate-500 dark:text-slate-400">No students match your filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 dark:border-slate-800">
        <span className="text-xs text-slate-500 dark:text-slate-400">Page {current} of {totalPages}</span>
        <div className="flex items-center gap-1">
          <button
            data-testid="page-prev"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={current === 1}
            className="h-8 w-8 flex items-center justify-center rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            data-testid="page-next"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={current === totalPages}
            className="h-8 w-8 flex items-center justify-center rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
