// Reports — Batch Report & Individual Student Report, built on the consented
// analytics channel + mentor-test records.
//
// Batch Report:  till-date cohort performance with a date range filter
//                (All time / Monthly / Weekly), weekly progress chart,
//                subject averages, mastery distribution, weak chapters and
//                who is progressing vs falling behind.
// Student Report: one student's complete journey from joining till date —
//                mastery journey chart, chapter table, tests (MCQ scores +
//                paper self-evaluation marks), weaknesses, recommendations.
import { useMemo, useState } from 'react';
import { Download, FileBarChart2, TrendingDown, TrendingUp, UserRound, UserSquare2 } from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Area, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, PieChart, Pie, Cell, LineChart,
} from 'recharts';
import { useBatchAnalyticsReport, useStudentReportAnalytics, useStudentsList } from '@/api/hooks-content';
import { BandBadge } from '@/components/content/ContentBadges';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';

const TABS = [
  { key: 'batch', label: 'Batch Report', icon: FileBarChart2 },
  { key: 'student', label: 'Student Report', icon: UserSquare2 },
];

const RANGES = [
  { key: 'all', label: 'All time' },
  { key: 'month', label: 'Monthly' },
  { key: 'week', label: 'This week' },
];

const BAND_LABELS = ['Not assessed', 'Weak', 'Medium', 'Strong', 'Mastered'];
const BAND_COLORS = ['#94A3B8', '#F43F5E', '#F59E0B', '#2563EB', '#10B981'];
const PIE_COLORS = { 'Not assessed': '#94A3B8', Weak: '#F43F5E', Medium: '#F59E0B', Strong: '#2563EB', Mastered: '#10B981' };
const axisTick = { fill: '#64748B', fontSize: 11 };

const fmtWeek = (iso) => {
  try { return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }); }
  catch { return iso; }
};
const fmtDate = (iso) => {
  try { return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); }
  catch { return iso || '—'; }
};
const monthsSince = (iso) => {
  try {
    const days = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 86400000));
    return days < 60 ? `${days} days` : `${Math.round(days / 30)} months`;
  } catch { return ''; }
};

function ChartTooltip({ active, payload, label, suffix = '' }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 shadow-lg text-xs">
      <div className="font-semibold text-slate-900 dark:text-white mb-1">{label}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.color || p.fill }} />
          <span className="text-slate-600 dark:text-slate-300">{p.name}:</span>
          <span className="font-semibold text-slate-900 dark:text-white">{p.value}{suffix}</span>
        </div>
      ))}
    </div>
  );
}

function Kpi({ label, value, sub, accent = 'text-slate-900 dark:text-white' }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
      <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-slate-500">{label}</div>
      <div className={cn('text-2xl font-bold mt-1', accent)}>{value}</div>
      {sub ? <div className="text-[11px] text-slate-400 mt-0.5">{sub}</div> : null}
    </div>
  );
}

function PanelTitle({ icon: Icon, children, right }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      {Icon ? <Icon className="w-4 h-4 text-[#2563EB]" /> : null}
      <h3 className="font-heading font-semibold text-slate-900 dark:text-white">{children}</h3>
      <div className="ml-auto">{right}</div>
    </div>
  );
}

const Panel = ({ children, className }) => (
  <div className={cn('bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5', className)}>{children}</div>
);

// ─────────────────────────────── BATCH REPORT ───────────────────────────────

function BatchReport({ onExportData }) {
  const [range, setRange] = useState('all');
  const { data, isLoading } = useBatchAnalyticsReport(range);
  const k = data?.kpis || {};

  useMemo(() => { if (data && onExportData) onExportData(data); }, [data, onExportData]);

  const pieData = Object.entries(data?.bandDistribution || {})
    .map(([name, value]) => ({ name, value, color: PIE_COLORS[name] }))
    .filter((d) => d.value > 0);

  return (
    <div className="space-y-4">
      {/* Range selector */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 mr-1">Date range</span>
        {RANGES.map((r) => (
          <button
            key={r.key}
            onClick={() => setRange(r.key)}
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors',
              range === r.key
                ? 'bg-[#2563EB] text-white border-[#2563EB]'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-[#2563EB]',
            )}
          >
            {r.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-400">Till date · {range === 'week' ? 'current week' : range === 'month' ? 'last 5 weeks' : 'everything synced'}</span>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {isLoading ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />) : (
          <>
            <Kpi label="Students sharing" value={k.students ?? 0} sub="consent ON" />
            <Kpi label="Chapters covered" value={k.chaptersCovered ?? 0} sub="of 94 in syllabus" />
            <Kpi label="Avg mastery" value={k.avgMasteryScore != null ? `${k.avgMasteryScore}/4` : '—'} sub={BAND_LABELS[Math.round(k.avgMasteryScore || 0)]} />
            <Kpi label="Tests given" value={k.testsGiven ?? 0} sub="MCQ + paper" />
            <Kpi label="Avg MCQ test" value={k.avgTestPct == null ? '—' : `${k.avgTestPct}%`} accent={k.avgTestPct >= 60 ? 'text-emerald-600' : 'text-amber-600'} />
            <Kpi label="Self marks due" value={k.pendingSelfMarks ?? 0} sub="paper evaluations" accent={k.pendingSelfMarks ? 'text-amber-600' : undefined} />
          </>
        )}
      </div>

      {/* Weekly progress */}
      <Panel>
        <PanelTitle icon={TrendingUp}>Weekly batch progress</PanelTitle>
        {isLoading ? <Skeleton className="h-[260px] w-full" /> : (data?.weeks || []).length === 0 ? (
          <p className="text-sm text-slate-500">No weekly snapshots in this range yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data.weeks} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
              <defs>
                <linearGradient id="masteryGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563EB" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#2563EB" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240 / 0.7)" />
              <XAxis dataKey="weekStart" tickFormatter={fmtWeek} tick={axisTick} axisLine={false} tickLine={false} />
              <YAxis yAxisId="left" domain={[0, 4]} ticks={[0, 1, 2, 3, 4]} tick={axisTick} axisLine={false} tickLine={false} />
              <YAxis yAxisId="right" orientation="right" allowDecimals={false} tick={axisTick} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
              <Bar yAxisId="right" dataKey="testsGiven" name="Tests given" fill="#C7D2FE" radius={[6, 6, 0, 0]} barSize={18} />
              <Area yAxisId="left" type="monotone" dataKey="avgBandScore" name="Avg mastery (0–4)" stroke="#2563EB" strokeWidth={2.5} fill="url(#masteryGrad)" />
              <Line yAxisId="right" type="monotone" dataKey="activeStudents" name="Active students" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </Panel>

      {/* Progressing vs falling behind */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel>
          <PanelTitle icon={TrendingUp} right={<span className="text-xs font-bold text-emerald-600">{(data?.progressing || []).length} students</span>}>
            Progressing well
          </PanelTitle>
          {isLoading ? <Skeleton className="h-24 w-full" /> : (data?.progressing || []).length === 0 ? (
            <p className="text-sm text-slate-500">No clearly improving students in this range.</p>
          ) : (
            <div className="space-y-2">
              {(data?.progressing || []).map((s) => (
                <div key={s.studentId} className="flex items-center gap-3 border border-emerald-100 dark:border-emerald-900/50 bg-emerald-50/50 dark:bg-emerald-500/5 rounded-lg px-3 py-2.5">
                  <TrendingUp className="w-4 h-4 text-emerald-600 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{s.name}</div>
                    <div className="text-xs text-slate-500 truncate">{s.batch || '—'} · improving in {s.chapters.join(', ')}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel>
          <PanelTitle icon={TrendingDown} right={<span className="text-xs font-bold text-rose-600">{(data?.fallingBehind || []).length} students</span>}>
            Needs attention
          </PanelTitle>
          {isLoading ? <Skeleton className="h-24 w-full" /> : (data?.fallingBehind || []).length === 0 ? (
            <p className="text-sm text-slate-500">No declining or inactive students — great batch health.</p>
          ) : (
            <div className="space-y-2">
              {(data?.fallingBehind || []).map((s) => (
                <div key={s.studentId} className="flex items-center gap-3 border border-rose-100 dark:border-rose-900/50 bg-rose-50/50 dark:bg-rose-500/5 rounded-lg px-3 py-2.5">
                  <TrendingDown className="w-4 h-4 text-rose-600 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{s.name}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {s.batch || '—'} · {s.reason === 'declining_trend' ? `declining in ${s.chapters.join(', ')}` : s.reason.replace('_', ' ').replace('inactive ', 'no activity for ')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Subject averages + band distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel>
          <PanelTitle>Subject-wise mastery average</PanelTitle>
          {isLoading ? <Skeleton className="h-[240px] w-full" /> : (data?.subjectAverages || []).length === 0 ? (
            <p className="text-sm text-slate-500">No subject data yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart layout="vertical" data={data.subjectAverages} margin={{ top: 4, right: 16, left: 30, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240 / 0.7)" horizontal={false} />
                <XAxis type="number" domain={[0, 4]} ticks={[0, 1, 2, 3, 4]} tick={axisTick} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="subject" width={92} tick={{ fill: '#475569', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="avgScore" name="Avg mastery (0–4)" radius={[0, 6, 6, 0]} barSize={16}>
                  {(data.subjectAverages || []).map((s, i) => (
                    <Cell key={i} fill={BAND_COLORS[Math.round(s.avgScore)]} />
                  ))}
                </Bar>
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Panel>
        <Panel>
          <PanelTitle>Chapter mastery distribution</PanelTitle>
          {isLoading ? <Skeleton className="h-[240px] w-full" /> : pieData.length === 0 ? (
            <p className="text-sm text-slate-500">No mastery data yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Tooltip content={<ChartTooltip />} />
                <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={3}>
                  {pieData.map((d, i) => <Cell key={i} fill={d.color} stroke="none" />)}
                </Pie>
                <Legend verticalAlign="bottom" height={30} iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Panel>
      </div>

      {/* Weak chapters */}
      <Panel>
        <PanelTitle icon={UserRound} right={<span className="text-xs text-slate-400">cohort-wide weak chapters</span>}>Weak chapters in the batch</PanelTitle>
        {isLoading ? <Skeleton className="h-20 w-full" /> : (data?.weakChapters || []).length === 0 ? (
          <p className="text-sm text-slate-500">No weak chapters detected.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {(data?.weakChapters || []).map((c) => (
              <div key={c.chapterId} className="flex items-center gap-3 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2.5">
                <span className="font-mono text-xs text-slate-700 dark:text-slate-200">{c.chapterId}</span>
                <span className="text-xs text-slate-400">{c.subject || '—'}</span>
                <span className="ml-auto text-xs font-bold text-rose-600">{c.weakStudents} weak</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

// ─────────────────────────────── STUDENT REPORT ─────────────────────────────

function StudentReport({ onExportData }) {
  const { data: students } = useStudentsList();
  const list = students?.items || [];
  const [selected, setSelected] = useState('');
  const studentId = selected || list[0]?.studentId || '';
  const { data: report, isLoading } = useStudentReportAnalytics(studentId);
  const p = report?.profile || {};
  const t = report?.totals || {};

  useMemo(() => { if (report && onExportData) onExportData(report); }, [report, onExportData]);

  const initials = (p.studentName || studentId || '?').split(' ').map((x) => x[0]).join('').slice(0, 2).toUpperCase();

  return (
    <div className="space-y-4">
      {/* Student selector */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Student</span>
        <select
          value={studentId}
          onChange={(e) => setSelected(e.target.value)}
          className="h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm font-medium text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40 min-w-[240px]"
        >
          {list.map((s) => (
            <option key={s.studentId} value={s.studentId}>{s.studentName || s.studentId} — {s.studentId}</option>
          ))}
        </select>
        {!isLoading && !p.sharing && (
          <span className="text-xs font-semibold text-amber-600">MCQ sharing is OFF for this student — mastery sections are hidden.</span>
        )}
      </div>

      {isLoading ? <Skeleton className="h-72 w-full" /> : !report ? null : (
        <>
          {/* Profile header — joined till date */}
          <Panel>
            <div className="flex flex-wrap items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-[#2563EB] text-white flex items-center justify-center text-lg font-bold">{initials}</div>
              <div className="min-w-0">
                <div className="text-lg font-bold text-slate-900 dark:text-white">{p.studentName || studentId}</div>
                <div className="text-xs text-slate-500">{studentId}{p.batch ? ` · ${p.batch}` : ''}{p.group ? ` · ${p.group}` : ''}</div>
              </div>
              <div className="ml-auto text-right">
                <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-slate-500">Member since</div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">{fmtDate(p.joinedOn)}</div>
                <div className="text-xs text-slate-400">{monthsSince(p.joinedOn)} of mentorship · full record below</div>
              </div>
            </div>
          </Panel>

          {/* Journey KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <Kpi label="Chapters tracked" value={t.chaptersTracked ?? 0} />
            <Kpi label="Mastered" value={t.mastered ?? 0} accent="text-emerald-600" />
            <Kpi label="Weak chapters" value={t.weak ?? 0} accent={t.weak ? 'text-rose-600' : undefined} />
            <Kpi label="MCQ attempts" value={t.totalAttempts ?? 0} />
            <Kpi label="Tests given" value={t.testsGiven ?? 0} sub={t.pendingSelfMarks ? `${t.pendingSelfMarks} self marks due` : undefined} />
            <Kpi label="Avg MCQ test" value={t.avgMcqTestPct == null ? '—' : `${t.avgMcqTestPct}%`} accent={t.avgMcqTestPct >= 60 ? 'text-emerald-600' : 'text-amber-600'} />
          </div>

          {/* Mastery journey chart */}
          <Panel>
            <PanelTitle icon={TrendingUp}>Mastery journey — week by week since joining</PanelTitle>
            {(report.weeks || []).length === 0 ? (
              <p className="text-sm text-slate-500">Not enough weekly snapshots yet for this student.</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={report.weeks} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(226 232 240 / 0.7)" />
                  <XAxis dataKey="weekStart" tickFormatter={fmtWeek} tick={axisTick} axisLine={false} tickLine={false} />
                  <YAxis domain={[0, 4]} ticks={[0, 1, 2, 3, 4]} tick={axisTick} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="avgBandScore" name="Avg mastery (0–4)" stroke="#2563EB" strokeWidth={2.5} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="masteredCount" name="Chapters mastered" stroke="#10B981" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Panel>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Chapter mastery table */}
            <Panel>
              <PanelTitle>Chapter-wise mastery</PanelTitle>
              {(report.chapters || []).length === 0 ? (
                <p className="text-sm text-slate-500">No chapter summaries synced yet.</p>
              ) : (
                <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
                  {(report.chapters || []).map((c) => (
                    <div key={c.chapterId} className="flex items-center gap-2 text-xs border-b border-slate-100 dark:border-slate-800 py-1.5 last:border-0">
                      <span className="font-mono text-slate-600 dark:text-slate-300 w-44 shrink-0 truncate">{c.chapterId}</span>
                      <span className="text-slate-400 flex-1">{c.subject || '—'} · {c.attemptCount} attempts · {c.accuracyRange}%</span>
                      <BandBadge band={c.masteryBand} />
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            {/* Weaknesses + movement */}
            <Panel>
              <PanelTitle icon={TrendingDown}>Weaknesses & movement</PanelTitle>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-slate-500 mb-1.5">Improving chapters</div>
                  {(report.improvingChapters || []).length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {report.improvingChapters.map((c) => (
                        <span key={c} className="px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-100 dark:border-emerald-900/50 text-[11px] font-semibold">{c}</span>
                      ))}
                    </div>
                  ) : <p className="text-xs text-slate-400">None improving in the tracked window.</p>}
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-slate-500 mb-1.5">Declining chapters</div>
                  {(report.decliningChapters || []).length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {report.decliningChapters.map((c) => (
                        <span key={c} className="px-2 py-0.5 rounded-md bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-100 dark:border-rose-900/50 text-[11px] font-semibold">{c}</span>
                      ))}
                    </div>
                  ) : <p className="text-xs text-slate-400">No declining chapters.</p>}
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-slate-500 mb-1.5">Weak concepts</div>
                  {(report.weakConcepts || []).length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {report.weakConcepts.map((c) => (
                        <span key={c} className="px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-100 dark:border-amber-900/50 text-[11px] font-semibold">{c}</span>
                      ))}
                    </div>
                  ) : <p className="text-xs text-slate-400">No weak concepts flagged.</p>}
                </div>
              </div>
            </Panel>
          </div>

          {/* Test records */}
          <Panel>
            <PanelTitle icon={FileBarChart2} right={<span className="text-xs text-slate-400">every mentor test since joining</span>}>Test records</PanelTitle>
            {(report.tests || []).length === 0 ? (
              <p className="text-sm text-slate-500">No mentor tests synced from this student yet.</p>
            ) : (
              <div className="space-y-2">
                {(report.tests || []).map((test, i) => {
                  const pct = test.total && test.score != null ? Math.round((test.score / test.total) * 100) : null;
                  return (
                    <div key={i} className="flex items-center gap-3 border border-slate-100 dark:border-slate-800 rounded-lg px-3 py-2.5">
                      <span className={cn('shrink-0 px-2 py-1 rounded-full text-[10px] font-semibold', test.kind === 'paper-test' ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300' : 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300')}>
                        {test.kind === 'paper-test' ? 'Paper' : 'MCQ'}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{test.title}</div>
                        <div className="text-xs text-slate-400">{test.subject || '—'} · {fmtDate(test.at)}</div>
                      </div>
                      {test.score != null ? (
                        <div className="text-right shrink-0">
                          <span className={cn('text-sm font-bold', pct != null && pct < 60 ? 'text-amber-600' : 'text-emerald-600')}>{test.score}{test.total ? `/${test.total}` : ''}</span>
                          {pct != null ? <span className="text-xs text-slate-400 ml-1.5">{pct}%</span> : null}
                          {test.kind === 'paper-test' && test.selfMarks ? <div className="text-[10px] font-semibold text-violet-600 dark:text-violet-400">self-evaluated</div> : null}
                        </div>
                      ) : (
                        <span className="shrink-0 text-[11px] font-semibold text-amber-600">marks due</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>

          {/* Recommendations + follow-ups */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel>
              <PanelTitle>Recommended next actions</PanelTitle>
              {(report.recommendations || []).length === 0 ? (
                <p className="text-sm text-slate-500">No action needed right now.</p>
              ) : (
                <ul className="space-y-2 text-sm text-slate-700 dark:text-slate-200">
                  {(report.recommendations || []).map((r, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#2563EB] mt-1.5 shrink-0" /> {r}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel>
              <PanelTitle>Follow-up actions</PanelTitle>
              {(report.followups || []).length === 0 ? (
                <p className="text-sm text-slate-500">No follow-ups recorded for this student.</p>
              ) : (
                <div className="space-y-2">
                  {(report.followups || []).map((f) => (
                    <div key={f.followupId} className="text-sm border border-slate-200 dark:border-slate-800 rounded-lg p-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-slate-800 dark:text-slate-100">{f.title}</span>
                        <span className={cn('px-2 py-0.5 rounded-full text-[10px] font-semibold border', f.status === 'completed' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200')}>
                          {f.status}
                        </span>
                        <span className="ml-auto text-xs text-slate-400">{f.priority}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

// ───────────────────────────────── PAGE SHELL ───────────────────────────────

export default function Reports() {
  const [tab, setTab] = useState('batch');
  const [exportData, setExportData] = useState(null);

  const exportPDF = () => {
    const doc = new jsPDF();
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(16);
    doc.text('Ujjwal Pathak Mentorship', 14, 16);
    doc.setFontSize(12);
    doc.text(tab === 'batch' ? 'Batch Report — till date' : 'Student Report — full journey', 14, 24);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.text(`Generated: ${new Date().toLocaleString('en-IN')}   ·   Source: consented analytics + mentor test records`, 14, 30);

    if (tab === 'batch' && exportData?.weeks) {
      autoTable(doc, {
        startY: 36,
        head: [['Week of', 'Avg mastery (0-4)', 'Active students', 'Tests given']],
        body: exportData.weeks.map((w) => [fmtDate(w.weekStart), w.avgBandScore, w.activeStudents, w.testsGiven]),
        theme: 'grid',
        headStyles: { fillColor: [37, 99, 235] },
        styles: { fontSize: 8 },
      });
      autoTable(doc, {
        head: [['Progressing', 'Chapters improving']],
        body: (exportData.progressing || []).map((s) => [`${s.name} (${s.studentId})`, s.chapters.join(', ')]),
        theme: 'grid',
        headStyles: { fillColor: [16, 185, 129] },
        styles: { fontSize: 8 },
      });
      autoTable(doc, {
        head: [['Needs attention', 'Reason']],
        body: (exportData.fallingBehind || []).map((s) => [`${s.name} (${s.studentId})`, s.reason === 'declining_trend' ? `declining in ${s.chapters.join(', ')}` : s.reason]),
        theme: 'grid',
        headStyles: { fillColor: [244, 63, 94] },
        styles: { fontSize: 8 },
      });
    } else if (tab === 'student' && exportData?.totals) {
      const p = exportData.profile || {};
      const t = exportData.totals || {};
      doc.setFontSize(10);
      doc.text(`${p.studentName || exportData.studentId} · ${exportData.studentId} · ${p.batch || ''} · Member since ${p.joinedOn || '—'}`, 14, 37);
      autoTable(doc, {
        startY: 42,
        head: [['Chapters', 'Mastered', 'Weak', 'MCQ attempts', 'Tests given', 'Avg MCQ test']],
        body: [[t.chaptersTracked, t.mastered, t.weak, t.totalAttempts, t.testsGiven, t.avgMcqTestPct == null ? '—' : `${t.avgMcqTestPct}%`]],
        theme: 'grid',
        headStyles: { fillColor: [37, 99, 235] },
        styles: { fontSize: 8 },
      });
      autoTable(doc, {
        head: [['Chapter', 'Subject', 'Attempts', 'Accuracy', 'Band']],
        body: (exportData.chapters || []).map((c) => [c.chapterId, c.subject || '—', c.attemptCount, `${c.accuracyRange}%`, c.masteryBand]),
        theme: 'grid',
        headStyles: { fillColor: [37, 99, 235] },
        styles: { fontSize: 8 },
      });
      autoTable(doc, {
        head: [['Test', 'Type', 'Marks', 'Self-evaluated', 'Date']],
        body: (exportData.tests || []).map((x) => [x.title, x.kind, x.score != null ? `${x.score}/${x.total || '—'}` : 'marks due', x.selfMarks ? 'yes' : '—', fmtDate(x.at)]),
        theme: 'grid',
        headStyles: { fillColor: [119, 88, 214] },
        styles: { fontSize: 8 },
      });
    }

    const pages = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pages; i += 1) {
      doc.setPage(i);
      doc.setFontSize(8);
      doc.text(`Page ${i} of ${pages}`, doc.internal.pageSize.getWidth() - 30, doc.internal.pageSize.getHeight() - 8);
    }
    doc.save(`${tab}-report.pdf`);
  };

  return (
    <div className="space-y-5" data-testid="reports-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex p-1 bg-slate-100 dark:bg-slate-800/60 rounded-lg">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              data-testid={`report-tab-${t.key}`}
              className={cn(
                'h-9 px-4 text-sm font-semibold rounded-md inline-flex items-center gap-2 transition-colors',
                tab === t.key ? 'bg-white dark:bg-slate-900 text-[#2563EB] shadow-sm' : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white',
              )}
            >
              <t.icon className="w-4 h-4" /> {t.label}
            </button>
          ))}
        </div>
        <button
          onClick={exportPDF}
          data-testid="export-btn"
          className="h-10 px-4 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center gap-2 transition-colors"
        >
          <Download className="w-4 h-4" /> Export Report
        </button>
      </div>

      {tab === 'batch' ? <BatchReport onExportData={setExportData} /> : <StudentReport onExportData={setExportData} />}
    </div>
  );
}
