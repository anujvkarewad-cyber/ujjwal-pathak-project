import { TrendingUp, TrendingDown } from 'lucide-react';
import { cn } from '@/utils/format';

export default function KPICard({ icon: Icon, label, value, suffix, delta, tone = 'blue', testid }) {
  const tones = {
    blue: 'bg-blue-50 text-[#2563EB] dark:bg-blue-500/10 dark:text-blue-400',
    emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400',
    rose: 'bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400',
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-400',
    slate: 'bg-slate-100 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300',
  };
  const isUp = (delta ?? 0) >= 0;
  return (
    <div
      data-testid={testid}
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-shadow duration-200"
    >
      <div className="flex items-start justify-between">
        <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center', tones[tone])}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        {typeof delta === 'number' && (
          <div className={cn('flex items-center gap-1 text-xs font-medium', isUp ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
            {isUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
            {Math.abs(delta)}%
          </div>
        )}
      </div>
      <div className="mt-5">
        <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{label}</div>
        <div className="mt-1.5 font-heading text-2xl md:text-3xl font-bold text-slate-900 dark:text-white">
          {value}{suffix && <span className="text-lg text-slate-400 dark:text-slate-500 ml-0.5">{suffix}</span>}
        </div>
      </div>
    </div>
  );
}
