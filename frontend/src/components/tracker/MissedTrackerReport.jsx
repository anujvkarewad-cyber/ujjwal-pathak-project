import { useMemo, useState } from 'react';
import {
  AlertCircle,
  CalendarDays,
  Check,
  Download,
  Minus,
  Search,
  X,
} from 'lucide-react';
import { useMissedTrackerReport } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';

const IST_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

function isoDayInIndia() {
  const parts = Object.fromEntries(IST_FORMATTER.formatToParts(new Date()).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function parseIsoDay(value) {
  const [year, month, day] = String(value || '').split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toIsoDay(value) {
  return value.toISOString().slice(0, 10);
}

function addDays(value, amount) {
  const day = parseIsoDay(value);
  day.setUTCDate(day.getUTCDate() + amount);
  return toIsoDay(day);
}

function mondayOfWeek(value) {
  const day = parseIsoDay(value);
  const distance = (day.getUTCDay() + 6) % 7;
  day.setUTCDate(day.getUTCDate() - distance);
  return toIsoDay(day);
}

function lastDayOfMonth(monthValue) {
  const [year, month] = String(monthValue || '').split('-').map(Number);
  return toIsoDay(new Date(Date.UTC(year, month, 0)));
}

function datesBetween(from, to) {
  const dates = [];
  for (let day = from; day <= to; day = addDays(day, 1)) dates.push(day);
  return dates;
}

function displayDate(value, options = {}) {
  if (!value) return '—';
  return parseIsoDay(value).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: options.year === false ? undefined : 'numeric',
    timeZone: 'UTC',
  });
}

function weekday(value) {
  return parseIsoDay(value).toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' });
}

function csvCell(value) {
  let text = String(value ?? '');
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function attendanceStatus(row, day) {
  if (day < row.expectedFrom) return 'Not expected';
  return (row.submittedDates || []).includes(day) ? 'Submitted' : 'Not submitted';
}

function downloadReport(data, dates, mode) {
  const headers = [
    'Student ID',
    'Student Name',
    'Group',
    'Batch',
    ...dates.map((day) => `${displayDate(day)} (${weekday(day)})`),
    'Expected Days',
    'Submitted Days',
    'Missed Days',
  ];
  const rows = (data.items || []).map((row) => [
    row.studentId,
    row.studentName,
    row.group,
    row.batch,
    ...dates.map((day) => attendanceStatus(row, day)),
    row.expectedDays,
    row.submittedDays,
    row.missedDays,
  ]);
  const csv = [headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n');
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `jan-2027-tracker-attendance-${mode}-${data.from}-to-${data.to}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function AttendanceCell({ status, day }) {
  if (status === 'Submitted') {
    return (
      <div title={`${displayDate(day)}: Submitted`} aria-label={`${displayDate(day)} submitted`} className="mx-auto flex h-7 w-7 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
        <Check className="h-4 w-4" strokeWidth={3} />
      </div>
    );
  }
  if (status === 'Not submitted') {
    return (
      <div title={`${displayDate(day)}: Not submitted`} aria-label={`${displayDate(day)} not submitted`} className="mx-auto flex h-7 w-7 items-center justify-center rounded-full bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300">
        <X className="h-4 w-4" strokeWidth={3} />
      </div>
    );
  }
  return (
    <div title={`${displayDate(day)}: Not expected`} aria-label={`${displayDate(day)} not expected`} className="mx-auto flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800">
      <Minus className="h-4 w-4" />
    </div>
  );
}

export default function MissedTrackerReport() {
  const today = isoDayInIndia();
  const [mode, setMode] = useState('weekly');
  const [weekAnchor, setWeekAnchor] = useState(today);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [search, setSearch] = useState('');
  const [missedOnly, setMissedOnly] = useState(true);

  const range = useMemo(() => {
    if (mode === 'monthly') {
      const from = `${month}-01`;
      const monthEnd = lastDayOfMonth(month);
      return { from, to: monthEnd > today ? today : monthEnd };
    }
    const from = mondayOfWeek(weekAnchor);
    const weekEnd = addDays(from, 6);
    return { from, to: weekEnd > today ? today : weekEnd };
  }, [mode, month, weekAnchor, today]);

  const dates = useMemo(() => datesBetween(range.from, range.to), [range.from, range.to]);
  const { data, isLoading, isFetching, error } = useMissedTrackerReport(range);

  const visibleItems = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data?.items || []).filter((row) => {
      if (missedOnly && row.missedDays === 0) return false;
      if (!term) return true;
      return `${row.studentName} ${row.studentId} ${row.group} ${row.batch}`.toLowerCase().includes(term);
    });
  }, [data?.items, missedOnly, search]);

  return (
    <section
      className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      data-testid="missed-tracker-report"
    >
      <div className="border-b border-slate-200 p-5 dark:border-slate-800">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-[#2563EB]" />
              <h2 className="font-heading text-lg font-bold text-slate-900 dark:text-white">
                Tracker Attendance · Jan 2027
              </h2>
            </div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Date-wise submitted and not-submitted status. Every calendar day counts.
            </p>
          </div>
          {data && (
            <button
              type="button"
              onClick={() => downloadReport(data, dates, mode)}
              className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              data-testid="tracker-attendance-download"
            >
              <Download className="h-4 w-4" /> Download CSV
            </button>
          )}
        </div>

        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="inline-flex h-10 rounded-lg bg-slate-100 p-1 dark:bg-slate-800" aria-label="Report period">
            {[
              ['weekly', 'Weekly'],
              ['monthly', 'Monthly'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                className={`rounded-md px-4 text-sm font-semibold transition-colors ${mode === value ? 'bg-white text-[#2563EB] shadow-sm dark:bg-slate-700 dark:text-blue-300' : 'text-slate-600 dark:text-slate-300'}`}
                data-testid={`tracker-attendance-${value}`}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === 'weekly' ? (
            <label className="space-y-1">
              <span className="block text-xs font-semibold text-slate-500 dark:text-slate-400">Any date in week</span>
              <input
                type="date"
                value={weekAnchor}
                max={today}
                onChange={(event) => { if (event.target.value) setWeekAnchor(event.target.value); }}
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                data-testid="tracker-attendance-week"
              />
            </label>
          ) : (
            <label className="space-y-1">
              <span className="block text-xs font-semibold text-slate-500 dark:text-slate-400">Month</span>
              <input
                type="month"
                value={month}
                max={today.slice(0, 7)}
                onChange={(event) => { if (event.target.value) setMonth(event.target.value); }}
                className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                data-testid="tracker-attendance-month"
              />
            </label>
          )}

          <div className="pb-2 text-xs text-slate-500 dark:text-slate-400">
            {displayDate(range.from)}–{displayDate(range.to)}{range.to === today ? ' · Live through today' : ''}
          </div>
          {isFetching && !isLoading && <div className="pb-2 text-xs font-semibold text-[#2563EB]">Updating…</div>}
        </div>
      </div>

      {isLoading && (
        <div className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-20 w-full" />)}
          </div>
          <Skeleton className="h-56 w-full" />
        </div>
      )}

      {!isLoading && error && (
        <div className="m-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700" role="alert">
          <div className="flex items-center gap-2 font-semibold">
            <AlertCircle className="h-4 w-4" /> Attendance report could not be generated
          </div>
          <div className="mt-1">{error.message}</div>
        </div>
      )}

      {!isLoading && !error && data && (
        <>
          <div className="grid grid-cols-2 gap-3 p-5 lg:grid-cols-4">
            {[
              ['Jan 2027 students', data.rosterCount],
              ['Calendar days', data.totalCalendarDays],
              ['Missed ≥ 1 day', data.studentsWithMissedDays],
              ['No missed days', data.studentsWithNoMissedDays],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800/60">
                <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{label}</div>
                <div className="mt-1 font-heading text-2xl font-bold text-slate-900 dark:text-white">{value}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-4">
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600 dark:text-slate-300">
              <span className="inline-flex items-center gap-1"><span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><Check className="h-3 w-3" /></span> Submitted</span>
              <span className="inline-flex items-center gap-1"><span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-rose-100 text-rose-700"><X className="h-3 w-3" /></span> Not submitted</span>
              <span className="inline-flex items-center gap-1"><span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-slate-400"><Minus className="h-3 w-3" /></span> Not expected</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setMissedOnly((value) => !value)}
                className={`h-9 rounded-lg border px-3 text-xs font-semibold ${missedOnly ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300' : 'border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300'}`}
                data-testid="tracker-attendance-missed-only"
              >
                {missedOnly ? 'Showing missed only' : 'Showing all students'}
              </button>
              <label className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search name or ID"
                  className="h-9 w-56 rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm dark:border-slate-700 dark:bg-slate-900"
                  data-testid="tracker-attendance-search"
                />
              </label>
            </div>
          </div>

          <div className="overflow-x-auto border-t border-slate-200 dark:border-slate-800">
            <table className="min-w-full border-separate border-spacing-0 text-sm" data-testid="tracker-attendance-table">
              <thead>
                <tr className="bg-slate-50 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">
                  <th className="sticky left-0 z-20 min-w-56 border-b border-r border-slate-200 bg-slate-50 px-5 py-3 text-left dark:border-slate-700 dark:bg-slate-800">Student</th>
                  <th className="min-w-24 border-b border-slate-200 px-3 py-3 text-left dark:border-slate-700">Group</th>
                  {dates.map((day) => (
                    <th key={day} className="min-w-14 border-b border-l border-slate-200 px-1 py-2 text-center dark:border-slate-700">
                      <div>{day.slice(-2)}</div>
                      <div className="mt-0.5 normal-case tracking-normal">{weekday(day)}</div>
                    </th>
                  ))}
                  <th className="min-w-20 border-b border-l border-slate-200 px-2 py-3 text-center dark:border-slate-700">Submitted</th>
                  <th className="min-w-20 border-b border-l border-slate-200 px-2 py-3 text-center dark:border-slate-700">Missed</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((row) => (
                  <tr key={row.studentId} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
                    <td className="sticky left-0 z-10 border-b border-r border-slate-100 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900">
                      <div className="font-semibold text-slate-900 dark:text-white">{row.studentName}</div>
                      <div className="text-xs text-slate-500">{row.studentId} · {row.batch}</div>
                    </td>
                    <td className="border-b border-slate-100 px-3 py-3 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300">{row.group}</td>
                    {dates.map((day) => (
                      <td key={day} className="border-b border-l border-slate-100 px-1 py-2 text-center dark:border-slate-800">
                        <AttendanceCell status={attendanceStatus(row, day)} day={day} />
                      </td>
                    ))}
                    <td className="border-b border-l border-slate-100 px-2 py-3 text-center font-bold text-emerald-600 dark:border-slate-800 dark:text-emerald-400">{row.submittedDays}</td>
                    <td className="border-b border-l border-slate-100 px-2 py-3 text-center dark:border-slate-800">
                      <span className="inline-flex min-w-9 justify-center rounded-full bg-rose-100 px-2.5 py-1 font-bold text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">{row.missedDays}</span>
                    </td>
                  </tr>
                ))}
                {visibleItems.length === 0 && (
                  <tr>
                    <td colSpan={dates.length + 4} className="px-5 py-10 text-center text-slate-500 dark:text-slate-400">
                      {missedOnly && data.studentsWithMissedDays === 0
                        ? 'Every Jan 2027 student submitted on every expected day in this period.'
                        : 'No students match the current search or filter.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
            Source: {data.source}. A genuine enrollment date is respected when present; otherwise counting starts from the displayed period’s first date as requested. Current-day status can change until a student submits.
          </div>
        </>
      )}
    </section>
  );
}
