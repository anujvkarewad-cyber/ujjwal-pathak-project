// Analytics → Weak Students / At-Risk / No Recent Activity (tabbed).
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ChevronRight, UserX } from 'lucide-react';
import { useAtRisk, useInactive, useWeakChapters } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const TABS = [
  { key: 'weak', label: 'Weak Students' },
  { key: 'atrisk', label: 'At-Risk Students' },
  { key: 'inactive', label: 'No Recent Activity' },
];

function WeakTab() {
  const { data, isLoading } = useWeakChapters();
  const items = data?.items || [];
  return (
    <div className="space-y-1.5">
      {isLoading && <Skeleton className="h-32 w-full" />}
      {!isLoading && items.map((c) => (
        <div key={c.chapterId} className="flex items-center gap-3 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2.5 text-sm">
          <UserX className="w-4 h-4 text-rose-500 shrink-0" />
          <span className="font-mono text-xs text-slate-700 dark:text-slate-200">{c.chapterId}</span>
          <span className="text-xs text-slate-500">cohort weak chapter</span>
          <span className="ml-auto text-xs font-semibold text-rose-600">{c.weakStudents} weak</span>
          <span className="text-xs text-slate-400">/ {c.totalStudents} assessed</span>
        </div>
      ))}
      {!isLoading && items.length === 0 && <p className="text-sm text-slate-500">No weak chapters detected.</p>}
    </div>
  );
}

function AtRiskTab() {
  const { data, isLoading } = useAtRisk();
  const items = data?.items || [];
  return (
    <div className="space-y-1.5">
      {isLoading && <Skeleton className="h-32 w-full" />}
      {!isLoading && items.map((s) => (
        <div key={s.studentId} className="flex items-center gap-3 border border-rose-200 dark:border-rose-900/60 rounded-lg px-3 py-2.5 text-sm bg-rose-50/50 dark:bg-rose-500/5">
          <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0" />
          <span className="font-mono text-xs text-slate-800 dark:text-slate-100">{s.studentId}</span>
          <span className="text-xs text-rose-600 font-medium">{s.reason?.replace(/_/g, ' ')}</span>
          <span className="text-xs text-slate-500">{s.decliningChapters} chapter(s) declining: {s.chapters?.join(', ')}</span>
          <Link to={`/analytics/students/${s.studentId}`} className="ml-auto inline-flex items-center text-xs font-semibold text-[#2563EB] hover:underline">
            Analysis <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      ))}
      {!isLoading && items.length === 0 && <p className="text-sm text-slate-500">No at-risk students detected.</p>}
    </div>
  );
}

function InactiveTab() {
  const { data, isLoading } = useInactive();
  const items = data?.items || [];
  return (
    <div className="space-y-1.5">
      {isLoading && <Skeleton className="h-32 w-full" />}
      {!isLoading && items.map((s, i) => (
        <div key={i} className="flex items-center gap-3 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2.5 text-sm">
          <span className="font-mono text-xs text-slate-700 dark:text-slate-200">{s.studentId}</span>
          <span className="font-mono text-xs text-slate-400">{s.chapterId}</span>
          <span className="ml-auto text-xs text-slate-500">last activity {s.lastActivityDate}</span>
          <Link to={`/analytics/students/${s.studentId}`} className="inline-flex items-center text-xs font-semibold text-[#2563EB] hover:underline">
            Analysis <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      ))}
      {!isLoading && items.length === 0 && <p className="text-sm text-slate-500">Everyone has recent activity.</p>}
    </div>
  );
}

export default function WeakAtRisk() {
  const [tab, setTab] = useState('weak');
  return (
    <div className="space-y-4" data-testid="weak-at-risk">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Weak & At-Risk Students</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Students needing mentor attention, by rule-based signals over consented summaries.</p>
      </div>
      <div className="flex gap-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              tab === t.key ? 'bg-[#2563EB] text-white' : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'weak' && <WeakTab />}
      {tab === 'atrisk' && <AtRiskTab />}
      {tab === 'inactive' && <InactiveTab />}
    </div>
  );
}
