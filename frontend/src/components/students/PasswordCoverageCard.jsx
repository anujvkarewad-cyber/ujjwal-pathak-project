import { useQuery } from '@tanstack/react-query';
import { KeyRound, RefreshCw } from 'lucide-react';
import { getCoverage } from '@/api/studentAdmin';
import { cn } from '@/utils/format';

/**
 * Progress meter for the sheet password ledger.
 *
 * The Students sheet is what the mentor reads and what the welcome mail is built
 * from, but the app only ever stores a bcrypt hash - so a password a student set
 * themselves can reach the sheet only at the moment they sign in. The backend does
 * exactly that on every successful login. This card shows how much is left to
 * fill; it disappears when nothing is pending.
 */
export default function PasswordCoverageCard() {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['password-coverage'],
    queryFn: () => getCoverage(false),
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading) return null;
  if (isError) {
    return (
      <div
        data-testid="password-coverage-unavailable"
        className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-2.5 text-xs text-slate-500 flex items-center gap-2"
      >
        <KeyRound className="h-3.5 w-3.5" />
        Password coverage could not be read right now ({error?.message || 'sheet unavailable'}).
        <button type="button" onClick={() => refetch()} className="ml-auto inline-flex items-center gap-1 font-semibold text-slate-600 dark:text-slate-300 hover:text-[#2563EB]">
          <RefreshCw className={cn('h-3 w-3', isFetching && 'animate-spin')} /> Try again
        </button>
      </div>
    );
  }

  const pending = data?.pending || [];
  if (!pending.length) return null;

  const bits = [
    data.marked ? `${data.marked} marked as changed in the app` : '',
    data.stale ? `${data.stale} still holding a password that no longer works` : '',
    data.blank ? `${data.blank} blank` : '',
  ].filter(Boolean);

  return (
    <div
      data-testid="password-coverage-card"
      className={cn(
        'rounded-xl border px-4 py-3',
        data.stale
          ? 'border-rose-300/70 bg-rose-50/70 dark:border-rose-500/30 dark:bg-rose-500/10'
          : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900',
      )}
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-0.5 h-8 w-8 shrink-0 rounded-lg bg-slate-100 dark:bg-slate-800 grid place-items-center">
          <KeyRound className="h-4 w-4 text-slate-600 dark:text-slate-300" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-heading text-sm font-semibold text-slate-800 dark:text-slate-100">
            Sheet passwords: {data.valid} of {data.total} students usable
            <span className="ml-2 text-xs font-normal text-slate-500">{data.usablePct}%</span>
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {bits.join(' · ')}. Nothing to do: when one of these students signs in, the app writes the
            password they used into the Students sheet automatically, and this number closes itself.
            {data.checkedAt ? ` Checked ${data.checkedAt.slice(0, 16).replace('T', ' ')} UTC.` : ''}
          </p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {pending.slice(0, 14).map((row) => (
              <li key={row.studentId}>
                <span
                  title={`${row.studentName || ''} — ${row.state}`}
                  className={cn(
                    'text-[11px] px-2 py-1 rounded-md',
                    row.state === 'stale'
                      ? 'bg-rose-100 dark:bg-rose-500/20 text-rose-700 dark:text-rose-300'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300',
                  )}
                >
                  {row.studentName ? `${row.studentName} · ` : ''}{row.studentId}
                </span>
              </li>
            ))}
            {pending.length > 14 && (
              <li className="text-[11px] px-2 py-1 text-slate-500">+{pending.length - 14} more</li>
            )}
          </ul>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          data-testid="password-coverage-refresh"
          className="h-8 px-3 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
          Re-check
        </button>
      </div>
    </div>
  );
}
