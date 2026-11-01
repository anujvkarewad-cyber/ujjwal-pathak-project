import { useEffect, useMemo, useState } from 'react';
import { CalendarOff, X } from 'lucide-react';
import {
  useCancelAttendance,
  useMarkMentorAbsent,
  useMarkMentorLeave,
} from '@/api/hooks';
import { cn } from '@/utils/format';

/**
 * Mentor-side leave / absent control for one student.
 *
 * Students declare their own leave / absent days from the app (owner spec
 * 14-Oct-2026). This dialog is the override: the mentor can mark a day absent
 * or set a leave range himself, e.g. when a student only says it on call.
 * Leave and absent days stay out of the attendance % but are shown separately
 * in the tracker.
 */
const LENGTHS = [1, 2, 3, 4, 5, 6, 7, 10, 14];

const addDays = (iso, days) => {
  const base = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(base.getTime())) return iso;
  base.setDate(base.getDate() + days);
  return base.toISOString().slice(0, 10);
};

const pretty = (iso) =>
  iso
    ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', {
        day: '2-digit',
        month: 'short',
      })
    : '';

export default function AttendanceModal({ student, date, open, onClose, existing = null }) {
  const [kind, setKind] = useState('absent');
  const [days, setDays] = useState(3);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  const markAbsent = useMarkMentorAbsent();
  const markLeave = useMarkMentorLeave();
  const cancelAttendance = useCancelAttendance();
  const saving = markAbsent.isPending || markLeave.isPending || cancelAttendance.isPending;

  useEffect(() => {
    if (!open) return;
    setKind(existing?.kind === 'leave' ? 'leave' : 'absent');
    setDays(3);
    setReason(existing?.reason || '');
    setError('');
  }, [open, student?.id, date, existing?.kind, existing?.reason]);

  const range = useMemo(() => ({ from: date, to: addDays(date, Math.max(0, days - 1)) }), [date, days]);

  if (!open || !student) return null;

  const removeExisting = async () => {
    if (!student) return;
    setError('');
    try {
      await cancelAttendance.mutateAsync(
        existing?.kind === 'leave'
          ? { leaveId: existing.recordId, studentId: student.id }
          : { studentId: student.id, date },
      );
      onClose();
    } catch (err) {
      setError(err?.message || 'Could not remove it. Please try again.');
    }
  };

  const submit = async () => {
    setError('');
    try {
      if (kind === 'absent') {
        await markAbsent.mutateAsync({ studentId: student.id, date, reason: reason.trim() });
      } else {
        await markLeave.mutateAsync({
          studentId: student.id,
          from: range.from,
          to: range.to,
          reason: reason.trim(),
        });
      }
      onClose();
    } catch (err) {
      setError(err?.message || 'Could not save. Please try again.');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-slate-900/40 p-0 sm:p-6">
      <div className="w-full sm:max-w-lg bg-white dark:bg-slate-900 rounded-t-2xl sm:rounded-2xl shadow-xl">
        <div className="flex items-start gap-3 border-b border-slate-200 dark:border-slate-800 p-5">
          <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center">
            <CalendarOff className="w-5 h-5 text-[#2563EB]" />
          </div>
          <div className="flex-1">
            <div className="font-heading font-bold text-slate-900 dark:text-white">
              {student.name} · {pretty(date)}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Leave and absent days are shown as their own status in the tracker and stay out of the
              submission rate.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {existing && (
            <div
              data-testid="attendance-existing"
              className={cn(
                'flex flex-wrap items-center gap-3 rounded-lg px-3 py-2 text-xs font-semibold',
                existing.kind === 'leave'
                  ? 'bg-blue-50 text-[#2563EB] dark:bg-blue-500/10'
                  : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
              )}
            >
              <span>
                Currently {existing.kind === 'leave' ? 'on leave' : 'absent'}
                {existing.reason ? ` — ${existing.reason}` : ''}
              </span>
              <button
                type="button"
                data-testid="attendance-remove"
                onClick={removeExisting}
                disabled={saving}
                className="ml-auto rounded-lg border border-current px-2.5 py-1 text-[11px] font-bold hover:bg-white/60 disabled:opacity-60"
              >
                Remove
              </button>
            </div>
          )}

          <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-800 p-0.5">
            {[
              { id: 'absent', label: 'Single absent day' },
              { id: 'leave', label: 'Leave (multiple days)' },
            ].map((option) => (
              <button
                key={option.id}
                type="button"
                data-testid={`attendance-kind-${option.id}`}
                onClick={() => setKind(option.id)}
                className={cn(
                  'h-9 px-3 text-xs font-semibold rounded-md transition-colors',
                  kind === option.id
                    ? 'bg-[#2563EB] text-white'
                    : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          {kind === 'leave' && (
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 mb-2">
                How many days
              </div>
              <div className="flex flex-wrap gap-1.5">
                {LENGTHS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setDays(value)}
                    className={cn(
                      'h-9 px-3 rounded-lg text-xs font-semibold border transition-colors',
                      days === value
                        ? 'border-[#2563EB] bg-blue-50 text-[#2563EB] dark:bg-blue-500/10'
                        : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800',
                    )}
                  >
                    {value}d
                  </button>
                ))}
              </div>
              <div className="mt-2 inline-flex items-center rounded-full bg-blue-50 dark:bg-blue-500/10 px-3 py-1 text-xs font-semibold text-[#2563EB]">
                {pretty(range.from)} → {pretty(range.to)}
              </div>
            </div>
          )}

          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500">
              Reason (optional)
            </span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={160}
              placeholder={kind === 'absent' ? 'Fever, function at home…' : 'Home visit, wedding…'}
              className="mt-2 w-full h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm outline-none focus:border-[#2563EB]"
            />
          </label>

          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="h-10 px-4 rounded-lg text-sm font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              data-testid="attendance-save"
              className="h-10 px-4 rounded-lg bg-[#2563EB] text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? 'Saving…' : kind === 'absent' ? 'Mark absent' : 'Save leave'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
