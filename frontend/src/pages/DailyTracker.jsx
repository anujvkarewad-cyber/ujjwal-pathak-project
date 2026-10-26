import SheetSourceStatus from '@/components/common/SheetSourceStatus';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle, Filter, RotateCcw, RefreshCw, MinusCircle, CalendarOff, PlaneTakeoff } from 'lucide-react';
import {
  useTrackerDay,
  useStudents,
  useSendFeedback,
  useCancelAttendance,
} from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import AttendanceModal from '@/components/tracker/AttendanceModal';
import MissedTrackerReport from '@/components/tracker/MissedTrackerReport';
import { cn } from '@/utils/format';
import { matchesStudentGroup, TRACKER_GROUP_FILTERS } from '@/utils/studentGroup';


export default function DailyTracker({ scopedBatch, scopedGroup, providedStudents, hideGrid = false } = {}) {
  const [batch, setBatch] = useState(scopedBatch || 'All Batches');
  const [group, setGroup] = useState(scopedGroup || 'All Groups');
  const [dayIndex, setDayIndex] = useState(13);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [attendanceStudent, setAttendanceStudent] = useState(null);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [feedbackPriority, setFeedbackPriority] = useState("Normal");
  const { data: rosterData } = useStudents({ enabled: !providedStudents });
  const sData = providedStudents ? { students: providedStudents } : rosterData;
  const {
    data,
    isLoading: trackerLoading,
    isFetching: trackerFetching,
    refetch: refreshTracker,
    error: trackerError,
  } = useTrackerDay({ dayIndex, batch });
  const sendFeedbackMutation = useSendFeedback();

  const batchOptions = useMemo(() => {
    const fromTracker = (data?.list || []).map((student) => student.batch).filter(Boolean);
    const supplied = (sData?.options?.batchOptions || []).filter((value) => value && value !== 'All Batches');
    return ['All Batches', ...new Set([...fromTracker, ...supplied])];
  }, [data?.list, sData?.options?.batchOptions]);
  const days = data?.days || [];
  const last7Start = Math.max(0, days.length - 7);
  const visibleRows = useMemo(() => {
    const groupByStudent = new Map(
      (sData?.students || []).map((student) => [String(student.id || '').trim().toUpperCase(), student.group || ''])
    );
    return (data?.list || [])
      .map((student) => ({
        ...student,
        group: student.group || groupByStudent.get(String(student.id || '').trim().toUpperCase()) || 'Unassigned',
      }))
      .filter((student) => matchesStudentGroup(student.group, group));
  }, [data?.list, group, sData?.students]);
  // Students whose own start date (joining / batch start / mentor override) is
  // after this day are not expected to have submitted — excluded from totals.
  const expectedRows = visibleRows.filter((student) => !student.notExpected);
  // status comes from the backend: present | leave | absent | missed. Older
  // payloads without it fall back to the submitted flag.
  const statusOf = (entry) => entry?.status || (entry?.submitted ? 'present' : 'missed');
  const submitted = expectedRows.filter((student) => student.entry?.submitted).length;
  const onLeave = expectedRows.filter((student) => statusOf(student.entry) === 'leave').length;
  const absentToday = expectedRows.filter((student) => statusOf(student.entry) === 'absent').length;
  const missed = expectedRows.filter((student) => statusOf(student.entry) === 'missed').length;
  const countable = Math.max(0, expectedRows.length - onLeave - absentToday);
  const rate = countable ? Math.round((submitted / countable) * 100) : 0;
  const excusedRows = expectedRows.filter((student) => ['leave', 'absent'].includes(statusOf(student.entry)));
  const selectedDate = days[dayIndex] || '';
  const cancelAttendance = useCancelAttendance();
  const isLoading = trackerLoading;
  const filtersActive = batch !== 'All Batches' || group !== 'All Groups';

  return (
    <>
    <div className="space-y-6" data-testid="daily-tracker-page">
      {data && <SheetSourceStatus source={data?.sources} />}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Submissions</div>
          <div className="mt-2 font-heading text-3xl font-bold text-emerald-600 dark:text-emerald-400" data-testid="tracker-submitted">{isLoading ? '—' : submitted}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Missed</div>
          <div className="mt-2 font-heading text-3xl font-bold text-rose-600 dark:text-rose-400" data-testid="tracker-missed">{isLoading ? '—' : missed}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">On leave</div>
          <div className="mt-2 font-heading text-3xl font-bold text-[#2563EB]" data-testid="tracker-on-leave">{isLoading ? '—' : onLeave}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Absent</div>
          <div className="mt-2 font-heading text-3xl font-bold text-amber-600 dark:text-amber-400" data-testid="tracker-absent">{isLoading ? '—' : absentToday}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Submission Rate</div>
          <div className="mt-2 font-heading text-3xl font-bold text-[#2563EB]" data-testid="tracker-rate">{isLoading ? '—' : `${rate}%`}</div>
          <div className="mt-1 text-[11px] text-slate-400">Leave/absent days not counted</div>
        </div>
      </div>

      {excusedRows.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="tracker-excused-panel">
          <div className="flex items-center gap-2">
            <PlaneTakeoff className="w-4 h-4 text-[#2563EB]" />
            <div className="font-heading font-bold text-slate-900 dark:text-white">Away on this day ({excusedRows.length})</div>
          </div>
          <div className="mt-3 space-y-2">
            {excusedRows.map((student) => {
              const kind = statusOf(student.entry);
              return (
                <div key={student.id} className="flex flex-wrap items-center gap-3 text-sm">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
                      kind === 'leave'
                        ? 'bg-blue-50 text-[#2563EB] dark:bg-blue-500/10'
                        : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
                    )}
                  >
                    {kind === 'leave' ? <PlaneTakeoff className="w-3.5 h-3.5" /> : <CalendarOff className="w-3.5 h-3.5" />}
                    {kind === 'leave' ? 'On leave' : 'Absent'}
                  </span>
                  <Link to={`/students/${student.id}`} className="font-semibold text-slate-800 dark:text-slate-100 hover:text-[#2563EB]">
                    {student.name}
                  </Link>
                  <span className="text-xs text-slate-500">{student.entry?.attendanceReason || 'No reason given'}</span>
                  <button
                    type="button"
                    onClick={() => {
                      const recordId = student.entry?.attendanceId || '';
                      cancelAttendance.mutate(
                        kind === 'leave'
                          ? { leaveId: recordId, studentId: student.id }
                          : { studentId: student.id, date: selectedDate },
                      );
                    }}
                    className="ml-auto text-xs font-semibold text-slate-500 hover:text-rose-600 underline-offset-2 hover:underline"
                  >
                    Cancel
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!hideGrid && <MissedTrackerReport scopedBatch={scopedBatch} scopedGroup={scopedGroup === 'Both Groups' ? 'both' : scopedGroup === 'Group 1' ? 'group1' : scopedGroup === 'Group 2' ? 'group2' : undefined} />}

      {trackerError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200" role="alert">
          Live tracker could not refresh: {trackerError.message || 'Please try again.'}
        </div>
      )}

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center gap-3">
          <Filter className="w-4 h-4 text-slate-400" />
          <label className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Batch</span>
            <select
              data-testid="tracker-batch"
              disabled={!!scopedBatch}
              value={batch}
              onChange={(e) => setBatch(e.target.value)}
              className="h-10 px-3 pr-8 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
            >
              {batchOptions.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Group</span>
            <select
              data-testid="tracker-group"
              disabled={!!scopedGroup}
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              className="h-10 px-3 pr-8 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
            >
              {TRACKER_GROUP_FILTERS.map(option => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
          {filtersActive && (
            <button
              type="button"
              data-testid="tracker-reset-filters"
              onClick={() => { setBatch('All Batches'); setGroup('All Groups'); }}
              className="h-10 px-3 inline-flex items-center gap-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
          )}
          <span className="text-xs text-slate-500 dark:text-slate-400" data-testid="tracker-filter-count">
            {isLoading ? 'Loading students…' : `${visibleRows.length} student${visibleRows.length === 1 ? '' : 's'}`}
          </span>
          <button
            type="button"
            onClick={() => refreshTracker()}
            disabled={trackerFetching}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            data-testid="tracker-refresh"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', trackerFetching && 'animate-spin')} />
            {trackerFetching ? 'Updating…' : 'Refresh'}
          </button>
          <div className="ml-auto flex items-center gap-1 overflow-x-auto">
            {days.slice(-7).map((d, i) => {
              const realIdx = last7Start + i;
              const active = realIdx === dayIndex;
              return (
                <button
                  key={d}
                  onClick={() => setDayIndex(realIdx)}
                  data-testid={`day-${d}`}
                  className={cn(
                    'h-9 px-3 rounded-lg text-xs font-medium transition-colors',
                    active ? 'bg-[#2563EB] text-white' : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                  )}
                >
                  {d.slice(-2)}
                </button>
              );
            })}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
           <thead>
  <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
    <th className="px-5 py-3">Student</th>
    <th className="px-5 py-3">Batch</th>
    <th className="px-5 py-3">Group</th>
    <th className="px-5 py-3">Hours</th>
    <th className="px-5 py-3">Subjects</th>
    <th className="px-5 py-3">Tomorrow Target</th>
    <th className="px-5 py-3">Reason</th>
    <th className="px-5 py-3">Mentor Support</th>
    <th className="px-5 py-3">Submission Time</th>
    <th className="px-5 py-3">Submitted</th>
    <th className="px-5 py-3">Study Proof</th>
    <th className="px-5 py-3">Actions</th>
  </tr>
</thead>
            <tbody>
  {isLoading &&
    Array.from({ length: 5 }).map((_, i) => (
      <tr
        key={i}
        className="border-b border-slate-100 dark:border-slate-800"
      >
        <td className="px-5 py-3" colSpan={12}>
          <Skeleton className="h-8 w-full" />
        </td>
      </tr>
    ))}

  {!isLoading &&
    visibleRows.map((s) => (
      
      <tr
        key={s.id}
        className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors"
      >
        <td className="px-5 py-3">
          <div className="flex items-center gap-3">
            <img
              src={s.avatar}
              alt=""
              className="w-8 h-8 rounded-full object-cover"
            />
            <div>
              <div className="font-semibold text-slate-900 dark:text-white">
                <Link
                  to={`/students/${s.id}`}
                  title={`Open ${s.name}'s full profile`}
                  className="hover:text-[#2563EB] dark:hover:text-blue-300 underline-offset-2 hover:underline"
                  data-testid={`tracker-day-profile-${s.id}`}
                >
                  {s.name}
                </Link>
              </div>
              <div className="text-xs text-slate-500">{s.id}</div>
            </div>
          </div>
        </td>

        <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
          {s.batch}
        </td>

        <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
          <span className="inline-flex rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-1 text-xs font-semibold">
            {s.group}
          </span>
        </td>

        <td className="px-5 py-3 font-semibold text-slate-800 dark:text-slate-200">
          {s.entry.hours}h
        </td>

        <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
          {s.entry.subjects || "—"}
        </td>

        <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
  {s.entry.tomorrowTarget || "—"}
</td>

<td className="px-5 py-3 text-slate-600 dark:text-slate-300">
  {s.entry.reason || "—"}
</td>

<td className="px-5 py-3">
  {s.entry.mentorSupport ? (
    <span
      className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${
        s.entry.mentorSupport === "Yes"
          ? "bg-emerald-100 text-emerald-700"
          : "bg-slate-100 text-slate-600"
      }`}
    >
      {s.entry.mentorSupport}
    </span>
  ) : (
    "—"
  )}
</td>

<td className="px-5 py-3 text-slate-600 dark:text-slate-300">
  {s.entry.submissionTime || "—"}
</td>

<td className="px-5 py-3">
          {s.notExpected ? (
            <span
              className="inline-flex items-center gap-1.5 text-slate-400 dark:text-slate-500 text-xs font-semibold"
              title={`Tracker starts ${s.effectiveStart || 'later'} for this student`}
            >
              <MinusCircle className="w-4 h-4" />
              Not expected
            </span>
          ) : statusOf(s.entry) === 'leave' ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 dark:bg-blue-500/10 px-2 py-1 text-xs font-semibold text-[#2563EB]"
              title={s.entry.attendanceReason || 'Student declared leave'}
              data-testid={`tracker-status-${s.id}`}
            >
              <PlaneTakeoff className="w-3.5 h-3.5" />
              On leave
            </span>
          ) : statusOf(s.entry) === 'absent' ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 dark:bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-700 dark:text-amber-300"
              title={s.entry.attendanceReason || 'Student reported absent'}
              data-testid={`tracker-status-${s.id}`}
            >
              <CalendarOff className="w-3.5 h-3.5" />
              Absent
            </span>
          ) : s.entry.submitted ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 text-xs font-semibold">
              <CheckCircle2 className="w-4 h-4" />
              Submitted
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-rose-600 dark:text-rose-400 text-xs font-semibold">
              <XCircle className="w-4 h-4" />
              Missed
            </span>
          )}
        </td>

        <td className="px-5 py-3">
  {s.entry.proofUrl ? (
  <button
    onClick={() => window.open(s.entry.proofUrl, "_blank", "noopener,noreferrer")}
    className="inline-flex items-center rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700"
  >
    View Proof
  </button>
) : (
  <span className="text-slate-400 text-xs">No Proof</span>
)}
</td>
        <td className="px-5 py-3">
  <button
    className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-700"
    onClick={() => {
  setSelectedStudent(s);
  setFeedbackMessage("");
  setFeedbackPriority("Normal");
  setFeedbackOpen(true);
}}
  >
    Send Feedback
  </button>
  <button
    type="button"
    title="Mark this student absent or on leave"
    data-testid={`tracker-attendance-${s.id}`}
    onClick={() => setAttendanceStudent(s)}
    className="ml-2 inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-1 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
  >
    <CalendarOff className="w-3.5 h-3.5" />
    Leave/Absent
  </button>
</td>
      </tr>
    ))}
  {!isLoading && visibleRows.length === 0 && (
    <tr>
      <td colSpan={12} className="px-5 py-12 text-center">
        <div className="font-semibold text-slate-700 dark:text-slate-200">No students match these filters</div>
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">Choose another batch or group, or reset the filters.</div>
      </td>
    </tr>
  )}
</tbody>
                  </table>
      </div>
    </div>
  </div>
    <AttendanceModal
      student={attendanceStudent}
      date={selectedDate}
      open={Boolean(attendanceStudent)}
      onClose={() => setAttendanceStudent(null)}
    />
    {feedbackOpen && (
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
    <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-[500px] p-6">

      <h2 className="text-xl font-bold mb-4">
        Send Feedback
      </h2>

      <p className="mb-3 text-sm text-slate-500">
        Student:
        <span className="font-semibold text-slate-900 dark:text-white ml-1">
          {selectedStudent?.name}
        </span>
      </p>

      <textarea
        rows={5}
        value={feedbackMessage}
        onChange={(e) => setFeedbackMessage(e.target.value)}
        placeholder="Write your feedback..."
        className="w-full border rounded-lg p-3 mb-4 dark:bg-slate-800"
      />

      <select
        value={feedbackPriority}
        onChange={(e) => setFeedbackPriority(e.target.value)}
        className="w-full border rounded-lg p-3 mb-5 dark:bg-slate-800"
      >
        <option>Normal</option>
        <option>Important</option>
        <option>Urgent</option>
      </select>

      <div className="flex justify-end gap-3">

        <button
          onClick={() => setFeedbackOpen(false)}
          className="px-4 py-2 rounded-lg bg-slate-300"
        >
          Cancel
        </button>

        <button
  onClick={() => {
    console.log("SEND BUTTON CLICKED");
    console.log("Student =", selectedStudent);
    console.log("Payload =", {
      studentId: selectedStudent.id,
      mentor: "Ujjwal Sir",
      message: feedbackMessage,
      priority: feedbackPriority,
    });

    sendFeedbackMutation.mutate(
      {
        studentId: selectedStudent.id,
        mentor: "Ujjwal Sir",
        message: feedbackMessage,
        priority: feedbackPriority,
      },
      {
        onSuccess: (res) => {
          console.log("SUCCESS", res);
          alert("Feedback sent successfully!");
          setFeedbackOpen(false);
        },
        onError: (err) => {
          console.error("ERROR", err);
          alert("Failed to send feedback.");
        },
      }
    );
  }}
  className="px-4 py-2 rounded-lg bg-blue-600 text-white"
>
  Send
</button>

      </div>

    </div>
  </div>
)}
    </>
);
}
