// Analytics → Group I / Group II analysis and Subject analysis.
import { useGroupAnalysis, useWeakChapters } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { BAND_COLORS } from '@/components/content/ContentBadges';

function GroupBars({ items }) {
  return (
    <div className="space-y-5">
      {items.map((g) => (
        <div key={g.group}>
          <div className="font-heading font-semibold text-sm text-slate-800 dark:text-slate-100 mb-2">{g.group}</div>
          <div className="space-y-2">
            {Object.entries(g.bandCounts).map(([band, count]) => (
              <div key={band} className="flex items-center gap-2 text-xs">
                <span className="w-24 text-slate-500">{band}</span>
                <div className="flex-1 h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${count ? Math.max(8, (count / Math.max(1, Object.values(g.bandCounts).reduce((a, b) => a + b, 0))) * 100) : 0}%`, backgroundColor: BAND_COLORS[band] }}
                  />
                </div>
                <span className="w-6 text-right font-semibold text-slate-700 dark:text-slate-200">{count}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function GroupAnalysis() {
  const { data, isLoading } = useGroupAnalysis();
  return (
    <div className="space-y-4" data-testid="group-analysis">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Group I / Group II Analysis</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Mastery band distribution across groups, from consented summaries.</p>
      </div>
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        {isLoading ? <Skeleton className="h-48 w-full" /> : <GroupBars items={data?.items || []} />}
        {!isLoading && !(data?.items || []).length && <p className="text-sm text-slate-500">No group data yet.</p>}
      </div>
    </div>
  );
}

export function SubjectAnalysis() {
  const { data, isLoading } = useWeakChapters();
  const items = data?.items || [];
  return (
    <div className="space-y-4" data-testid="subject-analysis">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Subject Analysis</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Cohort-level weak chapters ranked by share of weak students — the subject-level view of where the cohort needs help.</p>
      </div>
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">Chapter</th>
              <th className="px-4 py-3">Weak students</th>
              <th className="px-4 py-3">Assessed students</th>
              <th className="px-4 py-3">Weak share</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 4 }).map((_, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800"><td colSpan={4} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td></tr>
            ))}
            {!isLoading && items.map((c) => (
              <tr key={c.chapterId} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-200">{c.chapterId}</td>
                <td className="px-4 py-3 text-xs text-rose-600 font-semibold">{c.weakStudents}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{c.totalStudents}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-32 h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                      <div className="h-full rounded-full bg-rose-400" style={{ width: `${Math.round((c.weakStudents / Math.max(1, c.totalStudents)) * 100)}%` }} />
                    </div>
                    <span className="text-xs text-slate-500">{Math.round((c.weakStudents / Math.max(1, c.totalStudents)) * 100)}%</span>
                  </div>
                </td>
              </tr>
            ))}
            {!isLoading && items.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-slate-500">No data yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
