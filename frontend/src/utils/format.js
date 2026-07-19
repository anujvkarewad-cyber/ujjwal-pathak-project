export const pct = (n) => `${Math.round(n)}%`;

export const initials = (name = '') =>
  name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(p => p[0])
    .join('')
    .toUpperCase();

export const cn = (...c) => c.filter(Boolean).join(' ');

export const riskColor = (risk) => {
  if (risk === 'At Risk') return 'text-rose-600 bg-rose-50 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/20';
  if (risk === 'Watch') return 'text-amber-700 bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20';
  return 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20';
};

export const statusColor = (status) => {
  if (status === 'Active') return 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20';
  if (status === 'At Risk') return 'text-rose-600 bg-rose-50 border-rose-200 dark:bg-rose-500/10 dark:text-rose-400 dark:border-rose-500/20';
  return 'text-slate-600 bg-slate-100 border-slate-200 dark:bg-slate-700/40 dark:text-slate-300 dark:border-slate-600';
};
