// AI Content → Audit History. Every content transition, edit, approval,
// publish and analytics access (who / what / when / why).
import { useState } from 'react';
import { History } from 'lucide-react';
import { useAudit } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';

const ACTION_COLORS = {
  approve: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  approve_block: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  approve_chapter: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  reject: 'text-rose-600 bg-rose-50 border-rose-200',
  reject_block: 'text-rose-600 bg-rose-50 border-rose-200',
  request_changes: 'text-orange-600 bg-orange-50 border-orange-200',
  edit: 'text-blue-600 bg-blue-50 border-blue-200',
  publish: 'text-violet-600 bg-violet-50 border-violet-200',
  stage_10_staging: 'text-slate-600 bg-slate-50 border-slate-200',
};

export default function AuditHistory() {
  const [entityId, setEntityId] = useState('');
  const [action, setAction] = useState('');
  const { data, isLoading } = useAudit({ entityId, action });

  const items = data?.items || [];
  const actions = [...new Set(items.map((i) => i.action))];

  return (
    <div className="space-y-4" data-testid="audit-history">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Audit History</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Every edit, decision, chapter approval, publish and analytics read is recorded here.</p>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-end gap-3">
        <input
          className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs min-w-[220px]"
          placeholder="entity id (question / scenario / chapter)"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
        />
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">Action</span>
          <select className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs" value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All</option>
            {actions.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">When</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Entity</th>
              <th className="px-4 py-3">By</th>
              <th className="px-4 py-3">Detail</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 5 }).map((_, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800"><td colSpan={5} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td></tr>
            ))}
            {!isLoading && items.map((a, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{new Date(a.at).toLocaleString()}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${ACTION_COLORS[a.action] || 'text-slate-600 bg-slate-50 border-slate-200'}`}>
                    {a.action}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-300">{a.entityId || '—'} <span className="text-slate-400">({a.entityType || ''})</span></td>
                <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{a.by}</td>
                <td className="px-4 py-3 text-xs text-slate-500 max-w-[280px] truncate">{typeof a.detail === 'string' ? a.detail : JSON.stringify(a.detail || {})}</td>
              </tr>
            ))}
            {!isLoading && items.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500 flex items-center justify-center gap-2"><History className="w-4 h-4" /> No audit entries match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
