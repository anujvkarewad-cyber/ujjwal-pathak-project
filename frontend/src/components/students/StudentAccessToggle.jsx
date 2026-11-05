import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { setStudentAccess } from '@/api/studentAdmin';
import { cn } from '@/utils/format';

// Per-student app access toggle switch used inside every batch's
// "Daily tracker · Dates" table (and its Access OFF panel).
//
// Backend contract (`POST /api/student-dashboard/students/{id}/access`):
// - Turning access OFF requires a non-empty `reason` (shown to the student on login).
// - Turning access back ON takes an empty reason and restores login immediately.
// - `known` is false when a Sheet roster row has no Mongo `student_accounts` doc yet.
const INVALIDATE_KEYS = [
  ['tracker'],
  ['workspace-roster'],
  ['workspace-student-metrics'],
  ['students'],
  ['tracker-removed-students'],
];

const DEFAULT_QUICK_REASON = 'Daily tracker not submitted';

export default function StudentAccessToggle({
  studentId,
  studentName = '',
  enabled = true,
  known = true,
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');
  const queryClient = useQueryClient();
  const label = studentName || studentId;

  const mutation = useMutation({
    mutationFn: ({ next, why }) => setStudentAccess(studentId, next, why),
    onSuccess: (_res, { next }) => {
      INVALIDATE_KEYS.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
      queryClient.invalidateQueries({ queryKey: ['student-admin', studentId] });
      setAsking(false);
      setReason('');
      toast.success(next ? `App access turned ON for ${label}.` : `App access turned OFF for ${label}.`);
    },
    onError: (error) => toast.error(error?.message || 'Access could not be changed.'),
  });

  if (!known) {
    return (
      <span
        className="text-[11px] text-slate-400 dark:text-slate-500"
        title={`${label} has no app account yet, so access cannot be switched here.`}
        data-testid={`access-unavailable-${studentId}`}
      >
        —
      </span>
    );
  }

  if (asking) {
    const submit = (event) => {
      event.preventDefault();
      const why = reason.trim();
      if (!why) return;
      mutation.mutate({ next: false, why });
    };
    return (
      <form
        onSubmit={submit}
        className="flex min-w-44 flex-col gap-1.5 rounded-lg border border-rose-200 bg-rose-50/50 p-2 text-left dark:border-rose-900 dark:bg-rose-950/30"
        data-testid={`access-form-${studentId}`}
      >
        <input
          autoFocus
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={300}
          placeholder="Reason (student sees this)"
          aria-label={`Reason for turning off app access for ${label}`}
          className="h-7 w-full rounded border border-rose-200 bg-white px-2 text-[11px] text-slate-800 outline-none focus:border-rose-500 dark:border-rose-800 dark:bg-slate-900 dark:text-slate-100"
          data-testid={`access-reason-${studentId}`}
        />
        <button
          type="button"
          onClick={() => setReason(DEFAULT_QUICK_REASON)}
          className="self-start rounded border border-rose-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:bg-slate-900 dark:text-rose-300"
          data-testid={`access-preset-${studentId}`}
        >
          + {DEFAULT_QUICK_REASON}
        </button>
        <span className="flex items-center gap-1">
          <button
            type="submit"
            disabled={!reason.trim() || mutation.isPending}
            className="rounded bg-rose-600 px-2 py-1 text-[10px] font-bold text-white hover:bg-rose-700 disabled:opacity-50"
            data-testid={`access-confirm-${studentId}`}
          >
            {mutation.isPending ? 'Saving…' : 'Turn OFF'}
          </button>
          <button
            type="button"
            onClick={() => {
              setAsking(false);
              setReason('');
            }}
            disabled={mutation.isPending}
            className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
            data-testid={`access-cancel-${studentId}`}
          >
            Cancel
          </button>
        </span>
      </form>
    );
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={`App access for ${label}: ${enabled ? 'on' : 'off'}`}
      title={enabled ? `Turn OFF app access for ${label}` : `Turn app access back ON for ${label}`}
      disabled={mutation.isPending}
      data-testid={`access-toggle-${studentId}`}
      onClick={() => {
        if (enabled) setAsking(true);
        else mutation.mutate({ next: true, why: '' });
      }}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors disabled:opacity-50',
        enabled
          ? 'border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300'
          : 'border-rose-300 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300',
      )}
    >
      {mutation.isPending ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <span
          aria-hidden="true"
          className={cn(
            'relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors',
            enabled ? 'bg-emerald-600' : 'bg-rose-500',
          )}
        >
          <span
            className={cn(
              'inline-block h-3 w-3 rounded-full bg-white shadow transition-transform',
              enabled ? 'translate-x-3.5' : 'translate-x-0.5',
            )}
          />
        </span>
      )}
      <span>{enabled ? 'ON' : 'OFF'}</span>
    </button>
  );
}
