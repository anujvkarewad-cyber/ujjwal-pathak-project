// Analytics → Improvement Tracking. Improving vs declining students from
// weekly band snapshots synced by the device (same allowlisted fields, no raw answers).
import { Link } from 'react-router-dom';
import { ChevronRight, TrendingDown, TrendingUp } from 'lucide-react';
import { useImprovement } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import InlineError from '@/components/common/InlineError';

export default function ImprovementTracking() {
  const { data, isLoading, isError, error } = useImprovement();
  const items = data?.items || [];

  return (
    <div className="space-y-4" data-testid="improvement-tracking">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Improvement Tracking</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Weekly mastery-band snapshots (same allowlisted summary fields) show who is moving up and who is slipping.</p>
      </div>

      {isLoading && <Skeleton className="h-40 w-full" />}
      {!isLoading && isError && <InlineError error={error} title="Couldn’t load improvement tracking" />}
      {!isError && <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-600 mb-3">
            <TrendingUp className="w-4 h-4" /> Improving
          </div>
          <div className="space-y-1.5">
            {items.filter((i) => i.improvingChapters?.length).map((s) => (
              <div key={s.studentId} className="flex items-center gap-2 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs">
                <span className="font-mono font-semibold text-slate-700 dark:text-slate-200">{s.studentId}</span>
                <span className="text-slate-500">{s.improvingChapters.join(', ')}</span>
                <Link to={`/analytics/students/${s.studentId}`} className="ml-auto text-[#2563EB] font-semibold hover:underline inline-flex items-center">
                  View <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            ))}
            {!items.some((i) => i.improvingChapters?.length) && <p className="text-sm text-slate-500">No improving students yet.</p>}
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-rose-600 mb-3">
            <TrendingDown className="w-4 h-4" /> Declining
          </div>
          <div className="space-y-1.5">
            {items.filter((i) => i.decliningChapters?.length).map((s) => (
              <div key={s.studentId} className="flex items-center gap-2 border border-rose-200 dark:border-rose-900/60 bg-rose-50/40 dark:bg-rose-500/5 rounded-lg px-3 py-2 text-xs">
                <span className="font-mono font-semibold text-slate-800 dark:text-slate-100">{s.studentId}</span>
                <span className="text-rose-600">{s.decliningChapters.join(', ')}</span>
                <Link to={`/analytics/students/${s.studentId}`} className="ml-auto text-[#2563EB] font-semibold hover:underline inline-flex items-center">
                  View <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            ))}
            {!items.some((i) => i.decliningChapters?.length) && <p className="text-sm text-slate-500">No declining students — nice.</p>}
          </div>
        </div>
      </div>}
    </div>
  );
}
