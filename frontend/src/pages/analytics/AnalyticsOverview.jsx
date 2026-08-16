// Analytics → Overview. Cohort-level KPIs over consented MCQ summaries.
// Existing backend data (students, tracker, attendance, leaderboard, notes)
// keeps flowing through the existing Apps Script channel and remains visible
// on the existing Dashboard/Students pages.
import { Activity, BookOpen, CheckCircle2, ShieldAlert, Users } from 'lucide-react';
import { useAnalyticsOverview } from '@/api/hooks-content';
import KPICard from '@/components/dashboard/KPICard';
import { Skeleton } from '@/components/common/Skeleton';
import { BAND_COLORS } from '@/components/content/ContentBadges';

export default function AnalyticsOverview() {
  const { data: k, isLoading } = useAnalyticsOverview();

  return (
    <div className="space-y-6" data-testid="analytics-overview">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">All Students Overview</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Consented MCQ learning progress (summaries only — raw answers never leave the student device). Study activity, tracker, attendance and notes remain on the existing screens.
        </p>
      </div>

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white mb-3">Privacy model</h3>
          <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
            <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Students opt in via “Share learning progress with mentor”.</li>
            <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Only summaries sync: chapter, band, attempts, accuracy range, last activity, weak concept tags.</li>
            <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Raw MCQ answers, mastery history and adaptive history stay on the device.</li>
            <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> No student data is ever sent to the AI provider.</li>
            <li className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" /> Every mentor analytics read is written to the audit trail.</li>
          </ul>
          <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
            <Activity className="w-3.5 h-3.5" />
            {k.inactiveChapterCells} chapter cells show no recent activity (14-day threshold).
          </div>
        </div>
      </div>
    </div>
  );
}
