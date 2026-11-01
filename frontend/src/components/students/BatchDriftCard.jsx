import { useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, TriangleAlert, UserPlus } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { applyBatchDrift, getBatchDrift } from '@/api/studentAdmin';
import { cn } from '@/utils/format';

/**
 * Batch mismatch between the Students sheet and the student accounts.
 *
 * The student's own app shows the sheet (validateLogin is served by Apps Script),
 * while every audience decision - which test, which notes, which daily target,
 * which push, which batch rank - is taken from Mongo. A batch typed by hand into
 * the sheet therefore shows up nowhere and quietly keeps the student in the wrong
 * batch. This card makes the gap visible and closes it in one click.
 */
export default function BatchDriftCard() {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState(null);
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['batch-drift'],
    queryFn: () => getBatchDrift(false),
    staleTime: 60_000,
    retry: 1,
  });
  const sync = useMutation({
    mutationFn: (ids) => applyBatchDrift(ids),
    onSuccess: (result) => {
      setPicked(null);
      queryClient.invalidateQueries({ queryKey: ['batch-drift'] });
      queryClient.invalidateQueries({ queryKey: ['students'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['tracker'] });
      queryClient.invalidateQueries({ queryKey: ['leaderboard'] });
      toast.success(result?.message || 'Batch synced with the sheet.');
    },
    onError: (error) => toast.error(error?.message || 'Batch sync failed.'),
  });

  const drift = data?.drift || [];
  const needsImport = data?.needsImport || [];
  if (isLoading) return null;
  if (!drift.length && !needsImport.length) return null;

  const selected = picked ? drift.filter((row) => picked.includes(row.studentId)) : drift;

  const toggle = (id) => {
    const current = picked === null ? drift.map((row) => row.studentId) : picked;
    setPicked(current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  };

  return (
    <div
      data-testid="batch-drift-card"
      className="rounded-xl border border-amber-300/70 bg-amber-50/70 dark:bg-amber-500/10 dark:border-amber-500/30 p-4"
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-0.5 h-8 w-8 shrink-0 rounded-lg bg-amber-100 dark:bg-amber-500/20 grid place-items-center">
          <TriangleAlert className="h-4 w-4 text-amber-700 dark:text-amber-300" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-heading text-sm font-semibold text-amber-900 dark:text-amber-200">
            {drift.length
              ? `${drift.length} student${drift.length === 1 ? ' is' : 's are'} in a different batch in the sheet and in the app`
              : 'Some students are in the sheet but have no app account'}
          </h3>
          <p className="text-xs text-amber-800/80 dark:text-amber-200/70 mt-1">
            The student's own Profile reads the Students sheet; tests, notes, targets and pushes are chosen
            from the app account. Until they match, the student keeps getting the other batch's material.
            {data?.checkedAt ? ` Checked ${data.checkedAt.slice(0, 16).replace('T', ' ')} UTC.` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          data-testid="batch-drift-refresh"
          className="h-8 px-3 rounded-lg border border-amber-300 dark:border-amber-500/30 text-xs font-semibold text-amber-800 dark:text-amber-200 hover:bg-amber-100 dark:hover:bg-amber-500/20 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
          Re-check
        </button>
      </div>

      {!!drift.length && (
        <div className="mt-3 overflow-x-auto rounded-lg border border-amber-200 dark:border-amber-500/20 bg-white dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.14em] text-slate-500 border-b border-slate-100 dark:border-slate-800">
                <th className="p-2.5 w-8" aria-label="Select" />
                <th className="p-2.5">Student</th>
                <th className="p-2.5">Sheet (what the student sees)</th>
                <th className="p-2.5">App account (what decides their material)</th>
                <th className="p-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {drift.map((row) => {
                const on = !picked || picked.includes(row.studentId);
                return (
                  <tr key={row.studentId} className="border-b border-slate-50 dark:border-slate-800/60 last:border-0">
                    <td className="p-2.5">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => toggle(row.studentId)}
                        aria-label={`Select ${row.studentId}`}
                        data-testid={`batch-drift-pick-${row.studentId}`}
                      />
                    </td>
                    <td className="p-2.5">
                      <Link to={`/students/${row.studentId}`} className="font-semibold text-slate-800 dark:text-slate-100 hover:text-[#2563EB]">
                        {row.studentName || row.studentId}
                      </Link>
                      <span className="block text-[11px] text-slate-500">{row.studentId}</span>
                    </td>
                    <td className="p-2.5 text-slate-700 dark:text-slate-200">{row.sheetBatch || <em className="text-slate-400">blank</em>}</td>
                    <td className="p-2.5 text-slate-500">{row.mongoBatch || <em>unassigned</em>}</td>
                    <td className="p-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => sync.mutate([row.studentId])}
                        disabled={sync.isPending}
                        data-testid={`batch-drift-sync-${row.studentId}`}
                        className="h-7 px-2.5 rounded-md bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold transition-colors disabled:opacity-50"
                      >
                        Use sheet value
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="flex items-center justify-between gap-3 p-2.5 bg-slate-50/70 dark:bg-slate-900/60 border-t border-slate-100 dark:border-slate-800">
            <span className="text-[11px] text-slate-500">
              Only the Batch field is written. Passwords, group, attempt and history stay untouched, and every change is audited.
            </span>
            <button
              type="button"
              onClick={() => sync.mutate(selected.length === drift.length ? ['*'] : selected.map((row) => row.studentId))}
              disabled={sync.isPending || !selected.length}
              data-testid="batch-drift-apply"
              className="h-8 px-3.5 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold transition-colors disabled:opacity-50 whitespace-nowrap"
            >
              {sync.isPending ? 'Syncing…' : `Sync ${selected.length} to the app`}
            </button>
          </div>
        </div>
      )}

      {!!needsImport.length && (
        <div className="mt-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3">
          <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-200 inline-flex items-center gap-1.5">
            <UserPlus className="h-3.5 w-3.5" /> In the sheet, no app account yet ({needsImport.length})
          </h4>
          <p className="text-[11px] text-slate-500 mt-1">
            They can still sign in with their sheet password, but nothing stored in the app account exists for them - no tests,
            notes, daily targets, tracker or pushes - until the enrollment import has run. A batch sync does not create an account.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {needsImport.map((row) => (
              <li key={row.studentId}>
                <span className="text-[11px] px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                  {row.studentName ? `${row.studentName} · ` : ''}{row.studentId} · {row.sheetBatch}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
