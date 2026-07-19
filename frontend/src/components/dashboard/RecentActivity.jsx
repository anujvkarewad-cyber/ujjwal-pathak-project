import { CheckCircle2, AlertTriangle, Target, Calendar, StickyNote, Send } from 'lucide-react';
import { cn } from '@/utils/format';

const ICONS = {
  submission: { icon: Send, tone: 'bg-blue-50 text-[#2563EB] dark:bg-blue-500/10 dark:text-blue-400' },
  mcq: { icon: Target, tone: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400' },
  risk: { icon: AlertTriangle, tone: 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400' },
  attendance: { icon: CheckCircle2, tone: 'bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-400' },
  note: { icon: StickyNote, tone: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400' },
  event: { icon: Calendar, tone: 'bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300' },
};

export default function RecentActivity({ items }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 h-full" data-testid="recent-activity">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Recent Activity</h3>
        <button className="text-xs font-medium text-[#2563EB] hover:text-[#1D4ED8]" data-testid="view-all-activity">View all</button>
      </div>
      <ul className="space-y-1">
        {items.map((a) => {
          const meta = ICONS[a.type] || ICONS.event;
          const Icon = meta.icon;
          return (
            <li key={a.id} className="flex items-start gap-3 py-2.5 border-b border-slate-100 dark:border-slate-800 last:border-0">
              <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0', meta.tone)}>
                <Icon className="w-[16px] h-[16px]" strokeWidth={2.2} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-slate-800 dark:text-slate-200 leading-snug">
                  <span className="font-semibold">{a.student}</span> {a.action}
                </p>
                <span className="text-[11px] text-slate-500 dark:text-slate-400">{a.time}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
