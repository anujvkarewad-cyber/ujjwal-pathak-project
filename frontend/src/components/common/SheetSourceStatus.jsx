import { sheetSourceHealth } from '@/utils/sheetSourceHealth.mjs';

export default function SheetSourceStatus({ source }) {
  const health = sheetSourceHealth(source);
  const tone = health.state === 'warning'
    ? 'border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100'
    : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200';
  return <aside role="status" aria-live="polite" data-testid="sheet-source-status" data-source-state={health.state}
    className={`rounded-xl border px-4 py-3 text-sm ${tone}`}>
    <p className="font-semibold">{health.title}</p>
    <p className="mt-1 text-xs leading-relaxed">{health.detail}</p>
  </aside>;
}
