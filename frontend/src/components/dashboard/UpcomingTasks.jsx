import { CheckCircle2, Clock, Flag } from 'lucide-react';
import { cn } from '@/utils/format';

export default function UpcomingTasks({ tasks }) {
  const tones = {
    high: 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400',
    medium: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400',
    low: 'bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300',
  };
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 h-full" data-testid="upcoming-tasks">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Upcoming Tasks</h3>
        <span className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{tasks.length} tasks</span>
      </div>
      <ul className="space-y-2">
        {tasks.map((t) => (
          <li key={t.id} className="group flex items-start gap-3 p-3 rounded-lg border border-slate-100 dark:border-slate-800 hover:border-slate-200 dark:hover:border-slate-700 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors" data-testid={`task-${t.id}`}>
            <button className="mt-0.5 w-4 h-4 rounded border-2 border-slate-300 dark:border-slate-600 hover:border-[#2563EB] flex items-center justify-center transition-colors" aria-label="Mark complete">
              <CheckCircle2 className="w-3 h-3 text-transparent group-hover:text-[#2563EB]" />
            </button>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-200 leading-snug">{t.title}</p>
              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <Clock className="w-3 h-3" />
                <span>{t.due}</span>
              </div>
            </div>
            <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide', tones[t.priority])}>
              <Flag className="w-2.5 h-2.5" />
              {t.priority}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
