// Analytics → Overview. Cohort-level KPIs over consented MCQ summaries and
// mentor-test submissions. Raw MCQ answers never leave the student device.
import { Activity, BookOpen, CheckCircle2, ClipboardCheck, PenLine, ShieldAlert, ShieldCheck, Users } from 'lucide-react';
import { useAnalyticsOverview } from '@/api/hooks-content';
import KPICard from '@/components/dashboard/KPICard';
import { Skeleton } from '@/components/common/Skeleton';
import { BAND_COLORS } from '@/components/content/ContentBadges';

const fmtDate = (iso) => {
  try { return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso || '—'; }
};

export default function AnalyticsOverview() {
  const { data, isLoading } = useAnalyticsOverview();
  const k = data || {
    consentOnStudents: 0,
    studentsWithSummaries: 0,
    chaptersCovered: 0,
    openFollowups: 0,
    bandDistribution: { 'Not assessed': 0, Weak: 0, Medium: 0, Strong: 0, Mastered: 0 },
    inactiveChapterCells: 0,
    tests: { submissions: 0, studentsTested: 0, pendingSelfMarks: 0, avgMcqTestPct: null },
    recentTestSubmissions: [],
  };
  const t = k.tests || {};

  return (
    <div className="space-y-6" data-testid="analytics-overview">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">All Students Overview</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Consented learning progress: chapter mastery summaries plus every mentor test submission — MCQ scores and paper self-evaluation marks.
        </p>
      </div>

      {/* KPI row 1 — MCQ mastery channel */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)
          : (
            <>
              <KPICard icon={Users} label="Sharing enabled" value={k.consentOnStudents} tone="blue" testid="kpi-consent-on" />
              <KPICard icon={CheckCircle2} label="Students with data" value={k.studentsWithSummaries} tone="emerald" testid="kpi-students-data" />
              <KPICard icon={BookOpen} label="Chapters covered" value={k.chaptersCovered} suffix="/94" tone="violet" testid="kpi-chapters" />
              <KPICard icon={ShieldAlert} label="Open follow-ups" value={k.openFollowups} tone="amber" testid="kpi-followups" />
            </>
          )}
      </div>

      {/* KPI row 2 — mentor tests */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)
          : (
            <>
              <KPICard icon={ClipboardCheck} label="Test submissions" value={t.submissions ?? 0} tone="blue" testid="kpi-test-submissions" />
              <KPICard icon={Users} label="Students tested" value={t.studentsTested ?? 0} tone="emerald" testid="kpi-students-tested" />
              <KPICard icon={PenLine} label="Self marks due" value={t.pendingSelfMarks ?? 0} tone="amber" testid="kpi-marks-due" />
              <KPICard icon={CheckCircle2} label="Avg MCQ test score" value={t.avgMcqTestPct == null ? '—' : t.avgMcqTestPct} suffix={t.avgMcqTestPct == null ? '' : '%'} tone="violet" testid="kpi-avg-test" />
            </>
          )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Mastery band distribution */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white mb-3">Mastery band distribution</h3>
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <div className="space-y-2.5">
              {Object.entries(k.bandDistribution).map(([band, count]) => (
                <div key={band} className="flex items-center gap-3">
                  <span className="w-28 text-xs font-medium text-slate-600 dark:text-slate-300">{band}</span>
                  <div className="flex-1 h-3 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${count ? Math.max(6, (count / Math.max(1, k.studentsWithSummaries * 2)) * 100) : 0}%`, backgroundColor: BAND_COLORS[band] }}
                    />
                  </div>
                  <span className="w-10 text-right text-xs font-semibold text-slate-700 dark:text-slate-200">{count}</span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
            <Activity className="w-3.5 h-3.5" />
            {k.inactiveChapterCells} chapter cells show no recent activity (14-day threshold).
          </div>
        </div>

        {/* Recent test submissions */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white mb-3">Recent test submissions</h3>
          {isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (k.recentTestSubmissions || []).length === 0 ? (
            <p className="text-sm text-slate-500">No test submissions yet — they appear as soon as students give mentor tests in the app.</p>
          ) : (
            <div className="space-y-2">
              {(k.recentTestSubmissions || []).map((e, i) => {
                const pct = e.total && e.score != null ? Math.round((e.score / e.total) * 100) : null;
                return (
                  <div key={i} className="flex items-center gap-3 border-b border-slate-100 dark:border-slate-800 pb-2 last:border-0 last:pb-0">
                    <span className={`shrink-0 px-2 py-1 rounded-full text-[10px] font-semibold ${e.kind === 'paper-test' ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300' : 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300'}`}>
                      {e.kind === 'paper-test' ? 'Paper' : 'MCQ'}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">{e.studentName || e.studentId} · {e.title}</div>
                      <div className="text-[11px] text-slate-400">{fmtDate(e.at)}{e.selfMarks ? ' · self-evaluated' : ''}</div>
                    </div>
                    {e.score != null ? (
                      <span className={`shrink-0 text-xs font-bold ${pct != null && pct < 60 ? 'text-amber-600' : 'text-emerald-600'}`}>
                        {e.score}{e.total ? `/${e.total}` : ''}{pct != null ? ` · ${pct}%` : ''}
                      </span>
                    ) : (
                      <span className="shrink-0 text-[11px] font-semibold text-amber-600">marks due</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Privacy model */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white mb-3 flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-emerald-500" /> Privacy model</h3>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm text-slate-600 dark:text-slate-300">
          <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Students opt in via “Share learning progress with mentor”.</li>
          <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Only summaries sync: chapter, band, attempts, accuracy range, last activity, weak concept tags.</li>
          <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Raw MCQ answers and per-question history stay on the device.</li>
          <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Every mentor analytics read is written to the audit trail.</li>
        </ul>
      </div>
    </div>
  );
}
