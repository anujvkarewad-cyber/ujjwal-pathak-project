import { useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Mail, Phone, MapPin, Calendar, StickyNote, UsersRound, X, Power, PowerOff, Trash2, UserCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RiskBadge, StatusBadge } from '@/components/common/RiskBadge';
import { StudentWeeklyLine, StudentMonthlyBar, PerformanceRadar } from '@/components/charts/Charts';
import { Skeleton } from '@/components/common/Skeleton';
import { useStudent, useAddMentorNote } from '@/api/hooks';
import { getAdminState, setStudentAccess, removeStudent, restoreStudent } from '@/api/studentAdmin';
import { cn } from '@/utils/format';

const Stat = ({ label, value, suffix, tone = 'text-slate-900 dark:text-white' }) => (
  <div className="bg-slate-50 dark:bg-slate-800/40 rounded-lg p-4">
    <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{label}</div>
    <div className={cn('mt-1 font-heading text-2xl font-bold', tone)}>{value}{suffix && <span className="text-lg text-slate-400 ml-0.5">{suffix}</span>}</div>
  </div>
);

export default function StudentProfile() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: s, isLoading } = useStudent(id);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState('');
  const [offReason, setOffReason] = useState('');
  const [askingOff, setAskingOff] = useState(false);
  const addNote = useAddMentorNote();
  const queryClient = useQueryClient();
  const { data: adminState, isLoading: adminLoading } = useQuery({
    queryKey: ['student-admin', id],
    queryFn: () => getAdminState(id),
    enabled: !!id,
  });
  const accessMutation = useMutation({
    mutationFn: ({ enabled, reason }) => setStudentAccess(id, enabled, reason),
    onSuccess: (res) => {
      setAskingOff(false);
      setOffReason('');
      queryClient.invalidateQueries({ queryKey: ['student-admin', id] });
      toast.success(res?.accessEnabled ? 'App access turned ON.' : 'App access turned OFF.');
    },
    onError: (error) => toast.error(error?.message || 'Access could not be changed.'),
  });
  const removeMutation = useMutation({
    mutationFn: () => removeStudent(id, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['student-admin', id] });
      queryClient.invalidateQueries({ queryKey: ['tracker'] });
      queryClient.invalidateQueries({ queryKey: ['students'] });
      toast.success('Student removed. They can no longer log in.');
    },
    onError: (error) => toast.error(error?.message || 'Could not remove the student.'),
  });
  const restoreMutation = useMutation({
    mutationFn: () => restoreStudent(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['student-admin', id] });
      queryClient.invalidateQueries({ queryKey: ['tracker'] });
      queryClient.invalidateQueries({ queryKey: ['students'] });
      toast.success('Student restored.');
    },
    onError: (error) => toast.error(error?.message || 'Could not restore the student.'),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-40 w-full" />
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}
        </div>
      </div>
    );
  }

  if (!s) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center">
        <p className="text-slate-600 dark:text-slate-300">Student not found.</p>
        <Link to="/students" className="mt-4 inline-flex items-center gap-2 text-[#2563EB] font-medium">
          <ArrowLeft className="w-4 h-4" /> Back to students
        </Link>
      </div>
    );
  }

  const submitNote = (e) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    addNote.mutate({ id: s.id, note: noteText.trim() }, {
      onSuccess: () => { setNoteText(''); setNoteOpen(false); },
    });
  };

  const openBatchChange = () => navigate(`/batches?studentId=${encodeURIComponent(s.id)}&action=transfer`);

  return (
    <div className="space-y-6" data-testid="student-profile">
      <Link to="/students" className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300 hover:text-[#2563EB]" data-testid="back-to-students">
        <ArrowLeft className="w-4 h-4" /> Back to students
      </Link>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
        <div className="flex flex-col sm:flex-row gap-5">
          <img src={s.avatar} alt={s.name} className="w-24 h-24 rounded-2xl object-cover ring-4 ring-slate-100 dark:ring-slate-800" />
          <div className="flex-1 min-w-0">
            <div className="flex flex-col lg:flex-row lg:items-start gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-heading text-2xl font-bold text-slate-900 dark:text-white">{s.name}</h2>
                <StatusBadge status={s.status} />
                <RiskBadge risk={s.risk} />
              </div>
              <button
                type="button"
                onClick={openBatchChange}
                data-testid="change-batch-btn"
                className="lg:ml-auto inline-flex items-center justify-center gap-2 h-9 px-3 rounded-lg border border-blue-200 dark:border-blue-500/30 text-[#2563EB] dark:text-blue-300 bg-blue-50/70 dark:bg-blue-500/10 hover:bg-blue-100 dark:hover:bg-blue-500/20 text-sm font-semibold transition-colors"
              >
                <UsersRound className="w-4 h-4" /> Change Batch
              </button>
              <Link to={`/batches?studentId=${encodeURIComponent(s.id)}&action=transfer`} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 px-3 py-2 text-xs text-blue-600">Change batch / group · reviewed</Link>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{s.id} · {s.level} · {s.batch} · Attempt {s.attempt}</p>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Mail className="w-4 h-4 text-slate-400" />{s.email}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Phone className="w-4 h-4 text-slate-400" />{s.phone}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><MapPin className="w-4 h-4 text-slate-400" />{s.city}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Calendar className="w-4 h-4 text-slate-400" />Joined {s.joinedOn}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <Stat label="Attendance" value={s.attendance} suffix="%" tone={s.attendance >= 80 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'} />
        <Stat label="Study Hours / day" value={s.studyHours} suffix="h" />
        <Stat label="Weekly Submission" value={s.submissionRate} suffix="%" />
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6" data-testid="access-removal-card">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white text-lg">Access &amp; Removal</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Turn app access off for students who stop studying — they see the reason when they try to log in.
          Removing a student blocks login and hides them from tracker views, leaderboards and notifications (their data is kept).
        </p>
        {adminLoading || !adminState ? (
          <div className="mt-4"><Skeleton className="h-16 w-full" /></div>
        ) : (
          <div className="mt-5 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-slate-100 dark:border-slate-800 p-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">App access</span>
                  <span className={cn(
                    'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold',
                    adminState.accessEnabled
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300'
                      : 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300'
                  )} data-testid="access-status">
                    {adminState.accessEnabled ? 'ON' : 'OFF'}
                  </span>
                </div>
                {!adminState.accessEnabled && (
                  <p className="mt-1.5 text-xs text-rose-700 dark:text-rose-300">
                    Blocked{adminState.accessReason ? ` — ${adminState.accessReason}` : ''}
                    {adminState.accessUpdatedAt ? ` (since ${String(adminState.accessUpdatedAt).slice(0, 10)})` : ''}
                  </p>
                )}
              </div>
              {adminState.accessEnabled ? (
                <button
                  type="button"
                  onClick={() => setAskingOff((v) => !v)}
                  className="h-9 px-4 rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50 text-xs font-semibold inline-flex items-center gap-1.5 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-950/30"
                  data-testid="access-turn-off"
                >
                  <PowerOff className="w-3.5 h-3.5" /> Turn access OFF
                </button>
              ) : (
                <button
                  type="button"
                  disabled={accessMutation.isPending}
                  onClick={() => accessMutation.mutate({ enabled: true, reason: '' })}
                  className="h-9 px-4 rounded-lg border border-emerald-200 text-emerald-700 hover:bg-emerald-50 text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
                  data-testid="access-turn-on"
                >
                  <Power className="w-3.5 h-3.5" /> Turn access ON
                </button>
              )}
              {askingOff && (
                <form
                  className="w-full"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!offReason.trim()) return;
                    accessMutation.mutate({ enabled: false, reason: offReason.trim() });
                  }}
                >
                  <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">
                    Reason (shown to the student on login)
                  </label>
                  <textarea
                    value={offReason}
                    onChange={(e) => setOffReason(e.target.value)}
                    rows={2}
                    placeholder="e.g. Due to non-submission of tracker"
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm dark:text-slate-100"
                    data-testid="access-off-reason"
                  />
                  <div className="mt-2 flex items-center gap-2">
                    <button type="submit" disabled={accessMutation.isPending || !offReason.trim()} className="h-9 px-4 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold disabled:opacity-50">
                      {accessMutation.isPending ? 'Saving…' : 'Confirm — turn OFF'}
                    </button>
                    <button type="button" onClick={() => { setAskingOff(false); setOffReason(''); }} className="h-9 px-4 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300">
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-slate-100 dark:border-slate-800 p-4">
              <div>
                <span className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">Program membership</span>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                  {adminState.removed
                    ? `Removed${adminState.removedAt ? ` on ${String(adminState.removedAt).slice(0, 10)}` : ''}. Restore brings everything back.`
                    : 'Active in the program.'}
                </p>
              </div>
              {adminState.removed ? (
                <button
                  type="button"
                  disabled={restoreMutation.isPending}
                  onClick={() => restoreMutation.mutate()}
                  className="h-9 px-4 rounded-lg border border-emerald-200 text-emerald-700 hover:bg-emerald-50 text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/30"
                  data-testid="restore-student-btn"
                >
                  <UserCheck className="w-3.5 h-3.5" /> Restore student
                </button>
              ) : (
                <button
                  type="button"
                  disabled={removeMutation.isPending}
                  onClick={() => {
                    const ok = window.confirm(
                      `Remove ${s.name} (${s.id}) from the program?\n\n` +
                      'They will lose app access immediately and drop out of tracker views, ' +
                      'leaderboards and notifications. Their data is kept and you can restore them later.'
                    );
                    if (ok) removeMutation.mutate();
                  }}
                  className="h-9 px-4 rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50 text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-950/30"
                  data-testid="remove-student-btn"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Remove from program
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Weekly Progress</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Daily study hours</p>
          <StudentWeeklyLine data={s.weekly} />
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Performance Snapshot</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Multi-dimensional view</p>
          <PerformanceRadar student={s} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Monthly Progress</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Attendance & hours by week</p>
          <StudentMonthlyBar data={s.monthly} />
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <StickyNote className="w-4 h-4 text-[#2563EB]" />
            <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Mentor Notes</h3>
          </div>
          <ul className="space-y-3 max-h-64 overflow-y-auto pr-1">
            {s.mentorNotes.map((n, i) => (
              <li key={i} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{n.date}</div>
                <p className="text-sm text-slate-700 dark:text-slate-200 mt-1">{n.note}</p>
              </li>
            ))}
          </ul>
          <button onClick={() => setNoteOpen(true)} className="mt-3 w-full h-10 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold transition-colors" data-testid="add-note-btn">Add Note</button>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Daily Tracker · Last 5 days</h3>
        <div className="mt-4 grid grid-cols-5 gap-1.5">
          {s.tracker.map((d, i) => (
            <div key={i} title={`${d.date} · ${d.hours}h`} className={cn('aspect-square rounded-md flex items-center justify-center text-[10px] font-semibold', d.submitted ? 'bg-emerald-500/90 text-white' : 'bg-rose-100 dark:bg-rose-500/20 text-rose-600 dark:text-rose-400')}>
              {d.date.slice(-2)}
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" /> Submitted</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-rose-300 dark:bg-rose-500/40" /> Missed</span>
        </div>
      </div>

      {noteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm" onClick={() => setNoteOpen(false)}>
          <form onClick={(e) => e.stopPropagation()} onSubmit={submitNote} className="w-full max-w-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="add-note-dialog">
            <div className="flex items-center justify-between">
              <h4 className="font-heading font-semibold text-slate-900 dark:text-white">Add Mentor Note</h4>
              <button type="button" onClick={() => setNoteOpen(false)} className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-white" aria-label="Close">
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Notes are visible to {s.name} on their next session.</p>
            <textarea
              data-testid="note-text"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              rows={5}
              placeholder="Write a short note..."
              className="mt-3 w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200 resize-none"
            />
            <div className="mt-4 flex items-center justify-end gap-2">
              <button type="button" onClick={() => setNoteOpen(false)} className="h-9 px-4 rounded-lg border border-slate-200 dark:border-slate-800 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">Cancel</button>
              <button type="submit" disabled={addNote.isPending} data-testid="save-note-btn" className="h-9 px-4 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold transition-colors disabled:opacity-60">
                {addNote.isPending ? 'Saving...' : 'Save Note'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
