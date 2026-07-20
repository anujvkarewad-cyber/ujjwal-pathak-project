import { useState } from 'react';
import { CheckCircle2, XCircle, Filter } from 'lucide-react';
import { useTrackerDay, useStudents } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

export default function DailyTracker() {
  const [batch, setBatch] = useState('All Batches');
  const [dayIndex, setDayIndex] = useState(13);
  const { data: sData } = useStudents();
  const { data, isLoading } = useTrackerDay({ dayIndex, batch });

  const batchOptions = sData?.options?.batchOptions || ['All Batches'];
  const days = data?.days || [];
  const last7Start = Math.max(0, days.length - 7);

  return (
    <div className="space-y-6" data-testid="daily-tracker-page">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Submissions</div>
          <div className="mt-2 font-heading text-3xl font-bold text-emerald-600 dark:text-emerald-400">{data?.submitted ?? '—'}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Missed</div>
          <div className="mt-2 font-heading text-3xl font-bold text-rose-600 dark:text-rose-400">{data?.missed ?? '—'}</div>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Submission Rate</div>
          <div className="mt-2 font-heading text-3xl font-bold text-[#2563EB]">{data ? `${data.rate}%` : '—'}</div>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center gap-3">
          <Filter className="w-4 h-4 text-slate-400" />
          <select
            data-testid="tracker-batch"
            value={batch}
            onChange={(e) => setBatch(e.target.value)}
            className="h-10 px-3 pr-8 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
          >
            {batchOptions.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
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
        <td className="px-5 py-3" colSpan={11}>
          <Skeleton className="h-8 w-full" />
        </td>
      </tr>
    ))}

  {!isLoading &&
    (data?.list || []).map((s) => (
      
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
                {s.name}
              </div>
              <div className="text-xs text-slate-500">{s.id}</div>
            </div>
          </div>
        </td>

        <td className="px-5 py-3 text-slate-600 dark:text-slate-300">
          {s.batch}
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
          {s.entry.submitted ? (
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
    onClick={() => alert(`Send Feedback to ${s.name}`)}
  >
    Send Feedback
  </button>
</td>
      </tr>
    ))}
</tbody>
                  </table>
      </div>
    </div>
  </div>
);
}
