import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, Power, PowerOff } from 'lucide-react';
import { toast } from 'sonner';
import { setStudentAccess } from '@/api/studentAdmin';
import { cn } from '@/utils/format';

// Per-student app access switch, used inside the Daily Tracker date grid.
//
// Owner rule: a student who has stopped studying loses app access from the row
// where the mentor already sees the absence — no separate screen, no batch-wide
// switch. Turning access OFF always carries a reason, because the student is
// shown that reason when they try to log in (backend enforces it too: 400 when
// the reason is empty). Turning it back ON needs no reason and re-notifies the
// student about the days they missed, both handled server-side.
//
// `known` is false for roster entries with no app account yet (mongoReady false):
// there is nothing to switch, so the cell states that instead of failing a write.
const INVALIDATE = [
  ['tracker'],
  ['workspace-roster'],
  ['workspace-student-metrics'],
  ['students'],
  ['tracker-removed-students'],
];

export default function StudentAccessToggle({ studentId, studentName = '', enabled = true, known = true }) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState('');
  const queryClient = useQueryClient();
  const label = studentName || studentId;

  const mutation = useMutation({
    mutationFn: ({ next, why }) => setStudentAccess(studentId, next, why),
    onSuccess: (_res, { next }) => {
      INVALIDATE.forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
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
      <form onSubmit={submit} className="flex flex-col gap-1 text-left" data-testid={`access-form-${studentId}`}>
        <input
          autoFocus
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={300}
          placeholder="Reason (student sees this)"
          aria-label={`Reason for turning off app access for ${label}`}
          className="h-7 w-40 rounded border border-rose-200 bg-white px-1.5 text-[11px] text-slate-800 outline-none focus:border-rose-500 dark:border-rose-900 dark:bg-slate-900 dark:text-slate-100"
          data-testid={`access-reason-${studentId}`}
        />
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
            onClick={() => { setAsking(false); setReason(''); }}
            disabled={mutation.isPending}
            className="rounded border border-slate-200 px-2 py-1 text-[10px] font-semibold text-slate-500 dark:border-slate-700 dark:text-slate-400"
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
      onClick={() => { if (enabled) setAsking(true); else mutation.mutate({ next: true, why: '' }); }}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors disabled:opacity-50',
        enabled
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
          : 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300',
      )}
    >
      {mutation.isPending
        ? <Loader2 className="h-3 w-3 animate-spin" />
        : enabled ? <Power className="h-3 w-3" /> : <PowerOff className="h-3 w-3" />}
      {enabled ? 'ON' : 'OFF'}
    </button>
  );
}
