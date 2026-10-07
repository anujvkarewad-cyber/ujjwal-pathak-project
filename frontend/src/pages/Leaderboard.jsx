import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Trophy, Medal, Award, Crown, Info, AlertTriangle } from 'lucide-react';
import { useLeaderboard } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const PERIODS = [
  { key: 'overall', label: 'Overall' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
];

const SEGMENTS = [
  { key: 'batch', label: 'Batch' },
  { key: 'group', label: 'Group' },
];

const fmt = (value, digits = 1) =>
  Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';

function PodiumCard({ entry, rank, icon: Icon, tone, height }) {
  if (!entry) {
    return (
      <div className={cn('rounded-xl border border-dashed border-slate-200 dark:border-slate-800', height)} />
    );
  }
  return (
    <div className={cn('rounded-xl p-5 border border-slate-200 dark:border-slate-800 bg-gradient-to-b', tone, height, 'flex flex-col items-center justify-end text-center')}>
      <Icon className={cn('w-6 h-6 mb-2', rank === 1 ? 'text-amber-500' : rank === 2 ? 'text-slate-500' : 'text-orange-500')} />
      <div className="w-14 h-14 rounded-full bg-[#2563EB]/10 text-[#2563EB] font-heading font-bold grid place-items-center ring-4 ring-white dark:ring-slate-900 mb-2">
        {(entry.studentName || '?').slice(0, 1).toUpperCase()}
      </div>
      <div className="font-heading font-bold text-slate-900 dark:text-white text-sm">{entry.studentName}</div>
      <div className="text-xs text-slate-500 dark:text-slate-400">{entry.batch || entry.group}</div>
      <div className="mt-1 font-heading text-xl font-bold text-[#2563EB]">{fmt(entry.score, 1)}</div>
    </div>
  );
}

function SegmentBlock({ segment, segmentBy }) {
  // Cheap list filters: deriving them inline avoids memo dependency churn and is
  // clearer than caching a few hundred rows.
  const entries = segment.entries || [];
  const ranked = entries.filter((e) => !e.notRankedReason && e.rank > 0);
  const unranked = entries.filter((e) => e.notRankedReason);
  const top3 = ranked.slice(0, 3);

  return (
    <section className="space-y-4" data-testid={`segment-${segment.key}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-heading font-semibold text-slate-900 dark:text-white">
          {segment.label}
        </h2>
        <span className="text-xs text-slate-500 dark:text-slate-400 text-right">
          {segment.studentCount} student{segment.studentCount === 1 ? '' : 's'} · ranked within this {segmentBy}
          {segment.mcqUsed === false ? (
            <span className="block text-amber-600 dark:text-amber-400">
              score = hours + attendance only (MCQ not counted yet — {Math.round((segment.mcqCoverage || 0) * 100)}% of this group has synced attempts)
            </span>
          ) : null}
        </span>
      </div>

      {ranked.length >= 3 ? (
        <div className="grid grid-cols-3 gap-4 items-end">
          <PodiumCard entry={top3[1]} rank={2} icon={Medal} height="h-32"
            tone="from-slate-200 to-slate-100 dark:from-slate-700 dark:to-slate-800" />
          <PodiumCard entry={top3[0]} rank={1} icon={Crown} height="h-40"
            tone="from-amber-100 to-amber-50 dark:from-amber-500/20 dark:to-amber-500/5" />
          <PodiumCard entry={top3[2]} rank={3} icon={Award} height="h-24"
            tone="from-orange-100 to-orange-50 dark:from-orange-500/20 dark:to-orange-500/5" />
        </div>
      ) : null}

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2">
          <Trophy className="w-4 h-4 text-[#2563EB]" />
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">
            All ranked students
          </h3>
        </div>
        <div className="overflow-x-auto max-h-[32rem] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800/40">
              <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
                <th className="px-5 py-3 w-16">Rank</th>
                <th className="px-5 py-3">Student</th>
                <th className="px-5 py-3">Batch</th>
                <th className="px-5 py-3 text-right">Hours</th>
                <th className="px-5 py-3 text-right">Hrs / day</th>
                {segment.mcqUsed ? <th className="px-5 py-3 text-right">MCQ</th> : null}
                <th className="px-5 py-3 text-right">Attendance</th>
                <th className="px-5 py-3 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((s) => (
                <tr key={s.studentId}
                  className={cn('border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors',
                    s.status === 'Inactive' && 'opacity-60')}
                  data-testid={`lb-row-${s.studentId}`}>
                  <td className="px-5 py-3 font-heading font-bold text-slate-500 dark:text-slate-400">
                    #{s.rank}
                  </td>
                  <td className="px-5 py-3">
                    <Link to={`/students/${s.studentId}`} className="flex items-center gap-3 hover:text-[#2563EB]">
                      <span className="w-8 h-8 rounded-full bg-[#2563EB]/10 text-[#2563EB] font-semibold grid place-items-center text-xs">
                        {(s.studentName || '?').slice(0, 1).toUpperCase()}
                      </span>
                      <span>
                        <span className="font-semibold text-slate-900 dark:text-white">{s.studentName}</span>
                        {s.status === 'Inactive' ? (
                          <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-400">inactive</span>
                        ) : null}
                      </span>
                    </Link>
                  </td>
                  <td className="px-5 py-3 text-slate-600 dark:text-slate-300">{s.batch || '—'}</td>
                  <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">{fmt(s.hours, 1)}</td>
                  <td className="px-5 py-3 text-right text-slate-500 dark:text-slate-400">{fmt(s.hoursPerDay, 1)}</td>
                  {segment.mcqUsed ? (
                    <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                      {s.mcqAccuracy ? `${fmt(s.mcqAccuracy, 0)}%` : '—'}
                    </td>
                  ) : null}
                  <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                    {s.expectedDays ? `${s.attendance}%` : '—'}
                    <span className="block text-[10px] text-slate-400">
                      {s.submittedDays}/{s.expectedDays} days
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right font-heading font-bold text-[#2563EB]">{fmt(s.score, 1)}</td>
                </tr>
              ))}
              {!ranked.length ? (
                <tr>
                  <td colSpan={segment.mcqUsed ? 8 : 7} className="px-5 py-8 text-center text-slate-500 dark:text-slate-400">
                    No ranked students in this {segmentBy} yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {unranked.length ? (
          <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400">
            <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5" />
            Not ranked yet (not enrolled in this period): {unranked.map((u) => u.studentName).join(', ')}
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default function Leaderboard() {
  const [period, setPeriod] = useState('overall');
  const [segment, setSegment] = useState('batch');
  const { data, isLoading, error } = useLeaderboard({ period, segment });

  const segments = data?.segments || [];
  const totalRanked = segments.reduce((sum, s) => sum + (s.entries || []).length, 0);

  return (
    <div className="space-y-6" data-testid="leaderboard-page">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex p-1 bg-slate-100 dark:bg-slate-800/60 rounded-lg">
          {PERIODS.map((t) => (
            <button key={t.key} onClick={() => setPeriod(t.key)} data-testid={`tab-${t.key}`}
              className={cn('h-9 px-5 text-sm font-semibold rounded-md transition-colors',
                period === t.key
                  ? 'bg-white dark:bg-slate-900 text-[#2563EB] shadow-sm'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white')}>
              {t.label}
            </button>
          ))}
        </div>

        <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
          Rank within
          <select value={segment} onChange={(e) => setSegment(e.target.value)}
            data-testid="segment-select"
            className="h-9 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200">
            {SEGMENTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
        <Info className="w-3.5 h-3.5" />
        Score = study hours {data?.weights?.hours ?? 40} · attendance {data?.weights?.attendance ?? 30}
        {data?.weights?.mcq != null ? ` · MCQ ${data.weights.mcq}` : ''} · calendar starts {data?.historyFloor || '2026-09-28'} ·
        students joining later are measured from their own joining date
        {data?.weights?.mcqMode ? ` · MCQ mode: ${data.weights.mcqMode}` : ''}
        {data?.source?.roster ? ` · roster: ${data.source.roster}` : ''}
      </p>

      {error ? (
        <div className="rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/10 px-5 py-4 text-sm text-red-700 dark:text-red-300">
          Could not load the leaderboard: {error.message}
        </div>
      ) : null}

      {isLoading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4 items-end">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 w-full" />)}
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}

      {!isLoading && !error && !totalRanked ? (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 px-5 py-8 text-center text-slate-500 dark:text-slate-400">
          No students to rank yet.
        </div>
      ) : null}

      {segments.map((seg) => (
        <SegmentBlock key={seg.key} segment={seg} segmentBy={segment} />
      ))}
    </div>
  );
}
