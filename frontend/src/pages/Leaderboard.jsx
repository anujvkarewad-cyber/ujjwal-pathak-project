import SheetSourceStatus from '@/components/common/SheetSourceStatus';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Trophy, Medal, Award, Crown, Info, AlertTriangle, CalendarDays } from 'lucide-react';
import { useLeaderboard } from '@/api/hooks';
import { getWeeklyTops } from '@/api/leaderboard';
import { buildPosterSvg, posterCaption, posterPngDataUrl } from '@/utils/weeklyPoster';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const PERIODS = [
  { key: 'overall', label: 'Overall' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
];

const SEGMENTS = [
  { key: 'batch', label: 'Batch' },
  // The owner's chocolate rule: inside every batch, Group 1 / Group 2 / Both Groups is
  // its own leaderboard. Same boards the weekly Top 3 is taken from (segment=batch_group).
  { key: 'batch_group', label: 'Batch · Group' },
  { key: 'group', label: 'Group' },
];

const fmt = (value, digits = 1) =>
  Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const fmtDay = (iso, withYear = false) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${withYear ? ` ${d.getFullYear()}` : ''}`;
};

const fmtRange = (fromIso, toIso) => {
  if (!fromIso && !toIso) return '';
  const from = fromIso ? new Date(fromIso) : null;
  const to = toIso ? new Date(toIso) : null;
  if (!from || !to || Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return '';
  const sameMonth = from.getMonth() === to.getMonth();
  const left = sameMonth ? `${from.getDate()}` : fmtDay(fromIso);
  return `${left}–${fmtDay(toIso, true)}`;
};

const PLACE_ICONS = { 1: '🥇', 2: '🥈', 3: '🥉' };

function podiumText(week) {
  // Plain text for the WhatsApp group posts: one block per batch x group board.
  const lines = [`Weekly Top 3 · ${fmtRange(week.weekStart, week.weekEnd)}${week.isCurrent ? ' (this week)' : ''}`];
  (week.boards || []).forEach((b) => {
    lines.push('', b.label + (b.podiumEligible === false ? '  [group not set in the sheet - fix before the prize]' : ''));
    if (!b.top3?.length) lines.push('   no submissions');
    (b.top3 || []).forEach((t) => lines.push(`   ${t.place}. ${t.studentName} - ${fmt(t.hours, 1)} h`));
  });
  return lines.join('\n');
}

function WeeklyTops({ segment, batch, group }) {
  // "Kis week kaun top 3 tha" — one podium per calendar week, newest first. With
  // segment=batch_group each week also carries one podium per batch x group board.
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState('');
  const [poster, setPoster] = useState(null);   // { key, label, svg, caption, board }
  const [busy, setBusy] = useState('');

  const sayCopied = (what) => {
    setCopied(what);
    setTimeout(() => setCopied(''), 2500);
  };

  // The card is built from the endpoint's own board object, so the poster can
  // never disagree with the numbers on the screen. Only a CLOSED week gets a
  // poster, and only a board that is allowed a podium.
  const openPoster = (week, board) => {
    const full = { ...board, weekStart: week.weekStart, weekEnd: week.weekEnd };
    setPoster({
      key: `${week.weekStart}|${board.key}`,
      label: board.label,
      svg: buildPosterSvg(full),
      caption: posterCaption(full),
      board: full,
    });
  };

  const fileBase = (ext) => `weekly-top3-${poster?.board?.weekStart || 'week'}-${
    String(poster?.label || 'board').replace(/[^A-Za-z0-9]+/g, '-').toLowerCase()}.${ext}`;

  const downloadSvg = () => {
    if (!poster) return;
    const url = URL.createObjectURL(new Blob([poster.svg], { type: 'image/svg+xml;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = fileBase('svg');
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  const downloadPng = async () => {
    if (!poster) return;
    setBusy('png');
    try {
      const a = document.createElement('a');
      a.href = await posterPngDataUrl(poster.svg);
      a.download = fileBase('png');
      a.click();
    } catch (e) {
      // a browser that refuses to rasterise the SVG still gives a usable file
      downloadSvg();
    } finally {
      setBusy('');
    }
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setFailed(false);
    getWeeklyTops({ weeks: 6, segment, batch, group })
      .then((res) => { if (alive) setData(res); })
      .catch(() => { if (alive) setFailed(true); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [segment, batch, group]);

  if (loading) {
    return (
      <section className="space-y-3" data-testid="weekly-tops">
        <h2 className="font-heading font-semibold text-slate-900 dark:text-white">Weekly Top 3</h2>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36 w-full" />)}
        </div>
      </section>
    );
  }
  if (failed || !data?.weeks?.length) return null;

  return (
    <section className="space-y-3" data-testid="weekly-tops">
      <div className="flex items-center gap-2">
        <CalendarDays className="w-4 h-4 text-[#2563EB]" />
        <h2 className="font-heading font-semibold text-slate-900 dark:text-white">Weekly Top 3</h2>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          who topped each week ·{' '}
          {segment === 'batch_group' ? 'one podium per batch and group' : `within this ${segment}`}
        </span>
      </div>
      {poster ? (
        <div className="rounded-xl border border-[#E4BB55]/60 bg-slate-900 p-4 space-y-3" data-testid="poster-preview">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-200">
              {poster.label} · card for this week
            </p>
            <button type="button" onClick={() => setPoster(null)}
              className="text-xs font-semibold text-slate-300 hover:text-white">Close</button>
          </div>
          {/* the SVG is our own string; max-w keeps the preview usable on a laptop */}
          <div className="max-w-[300px] mx-auto [&_svg]:w-full [&_svg]:h-auto rounded-lg overflow-hidden"
            dangerouslySetInnerHTML={{ __html: poster.svg }} />
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button type="button" onClick={downloadPng} disabled={busy === 'png'}
              className="h-8 px-3 rounded-lg bg-[#2563EB] text-white text-xs font-semibold disabled:opacity-60">
              {busy === 'png' ? 'Rendering…' : 'Download PNG'}
            </button>
            <button type="button" onClick={downloadSvg}
              className="h-8 px-3 rounded-lg border border-slate-700 text-slate-200 text-xs font-semibold hover:border-slate-500">
              Download SVG
            </button>
            <button type="button"
              onClick={() => { navigator.clipboard?.writeText(poster.caption); sayCopied('poster'); }}
              className="h-8 px-3 rounded-lg border border-slate-700 text-slate-200 text-xs font-semibold hover:border-slate-500">
              {copied === 'poster' ? 'Caption copied ✓' : 'Copy caption'}
            </button>
          </div>
          <p className="text-[10px] text-slate-400 text-center">
            You post this into that group yourself — nothing here sends or pushes anything to students.
          </p>
        </div>
      ) : null}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {data.weeks.map((w) => (
          <div key={w.weekStart}
            className={cn('rounded-xl border p-4 bg-white dark:bg-slate-900',
              w.isCurrent
                ? 'border-[#2563EB]/40 ring-1 ring-[#2563EB]/20'
                : 'border-slate-200 dark:border-slate-800')}
            data-testid={`weekly-top-${w.weekStart}`}>
            <div className="flex items-baseline justify-between gap-2 mb-2">
              <span className="text-sm font-semibold text-slate-900 dark:text-white">
                {fmtRange(w.weekStart, w.weekEnd)}
              </span>
              {w.isCurrent ? (
                <span className="text-[10px] uppercase tracking-wide font-semibold text-[#2563EB]">
                  Current
                </span>
              ) : null}
            </div>
            {w.boards?.length ? (
              <div className="space-y-3">
                {w.boards.map((b) => (
                  <div key={b.key} data-testid={`weekly-board-${w.weekStart}-${b.key}`}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 truncate">
                        {b.label}
                      </span>
                      <span className="flex items-center gap-2 shrink-0">
                        <span className="text-[10px] text-slate-400 dark:text-slate-500">{b.studentCount} ranked</span>
                        {!w.isCurrent && b.podiumEligible !== false && b.top3?.length ? (
                          <button type="button" onClick={() => openPoster(w, b)}
                            data-testid={`poster-${w.weekStart}-${b.key}`}
                            className={cn('text-[10px] font-semibold hover:underline',
                              poster?.key === `${w.weekStart}|${b.key}` ? 'text-amber-500' : 'text-[#2563EB]')}>
                            {poster?.key === `${w.weekStart}|${b.key}` ? 'Showing ✓' : 'Poster'}
                          </button>
                        ) : null}
                      </span>
                    </div>
                    {b.podiumEligible === false ? (
                      <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">
                        these students have no group in the sheet — not counted for a group prize
                      </p>
                    ) : null}
                    <ul className="space-y-1 mt-1">
                      {(b.top3 || []).map((t) => (
                        <li key={t.studentId} className="flex items-center gap-2 text-sm">
                          <span className="w-5 text-center">{PLACE_ICONS[t.place] || `#${t.place}`}</span>
                          <Link to={`/students/${t.studentId}`}
                            className="flex-1 truncate font-medium text-slate-800 dark:text-slate-200 hover:text-[#2563EB]">
                            {t.studentName}
                          </Link>
                          <span className="text-xs text-slate-500 dark:text-slate-400">{fmt(t.hours, 1)}h</span>
                        </li>
                      ))}
                      {!b.top3?.length ? (
                        <li className="text-xs text-slate-400 dark:text-slate-500">No submissions in this board.</li>
                      ) : null}
                    </ul>
                  </div>
                ))}
                <button
                  type="button"
                  className="mt-1 text-[11px] font-semibold text-[#2563EB] hover:underline"
                  onClick={() => {
                    navigator.clipboard?.writeText(podiumText(w));
                    sayCopied(w.weekStart);
                  }}>
                  {copied === w.weekStart ? 'Copied ✓' : 'Copy the group lists'}
                </button>
              </div>
            ) : w.top3.length ? (
              <ul className="space-y-1.5">
                {w.top3.map((t) => (
                  <li key={t.studentId} className="flex items-center gap-2 text-sm">
                    <span className="w-5 text-center">{PLACE_ICONS[t.place] || `#${t.place}`}</span>
                    <Link to={`/students/${t.studentId}`}
                      className="flex-1 truncate font-medium text-slate-800 dark:text-slate-200 hover:text-[#2563EB]">
                      {t.studentName}
                    </Link>
                    <span className="text-xs text-slate-500 dark:text-slate-400">{fmt(t.hours, 1)}h</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-400 dark:text-slate-500">No submissions this week.</p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

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
      <div className="font-heading font-bold text-slate-900 dark:text-white text-sm">
        <Link to={`/students/${entry.studentId}`} title={`Open ${entry.studentName}'s full profile`} className="hover:text-[#2563EB] underline-offset-2 hover:underline">
          {entry.studentName}
        </Link>
      </div>
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
                <th className="px-5 py-3 w-24">This Week</th>
                <th className="px-5 py-3 w-24">Overall</th>
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
                  <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
                    {s.rankWeekly ? `#${s.rankWeekly}` : '—'}
                  </td>
                  <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
                    {s.rankOverall ? `#${s.rankOverall}` : '—'}
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
                  <td colSpan={segment.mcqUsed ? 10 : 9} className="px-5 py-8 text-center text-slate-500 dark:text-slate-400">
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

export default function Leaderboard({ scopedBatch, scopedGroup } = {}) {
  const [period, setPeriod] = useState('overall');
  const [segment, setSegment] = useState(scopedGroup ? 'batch_group' : 'batch');
  const [comparison, setComparison] = useState('group');
  const selectedBatch = comparison === 'all' ? undefined : scopedBatch;
  const selectedGroup = comparison === 'group' ? scopedGroup : undefined;
  const { data, isLoading, error } = useLeaderboard({ period, segment, batch: selectedBatch, group: selectedGroup });

  const segments = data?.segments || [];
  const totalRanked = segments.reduce((sum, s) => sum + (s.entries || []).length, 0);

  return (
    <div className="space-y-6" data-testid="leaderboard-page">
      {data && <SheetSourceStatus source={data?.source} />}
      {scopedBatch && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-3 text-xs"><span>Comparison:</span>{[['group', 'This group'], ['batch', 'Batch overall'], ['all', 'All existing boards']].map(([key, label]) => <button key={key} aria-pressed={comparison === key} onClick={() => { setComparison(key); setSegment(key === 'group' ? 'batch_group' : 'batch'); }} className={`rounded-md px-3 py-2 ${comparison === key ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600'}`}>{label}</button>)}<span className="text-slate-500">Existing ranking method; no new cross-batch scoring.</span></div>}
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
        {data?.from ? ` · window: ${fmtDay(data.from)} – ${fmtDay(data.to, true)}` : ''}
        {data?.weekStart ? ` · this week: ${fmtRange(data.weekStart, data.weekEnd)}` : ''}
      </p>

      <WeeklyTops segment={segment} batch={selectedBatch} group={selectedGroup} />

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
