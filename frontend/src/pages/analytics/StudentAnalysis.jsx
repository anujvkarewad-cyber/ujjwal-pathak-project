// Analytics → Student Profile Analysis (list). Joins consented analytics
// students with sharing state; opens the per-student analysis view.
import { Link } from 'react-router-dom';
import { ChevronRight, ShieldCheck, ShieldOff } from 'lucide-react';
import { useStudentsList } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import InlineError from '@/components/common/InlineError';

export default function StudentAnalysis() {
  const { data, isLoading, isError, error } = useStudentsList();
  const students = data?.items || [];

  return (
    <div className="space-y-4" data-testid="student-analysis-list">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Student Profile Analysis</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Students visible in the consent-based analytics channel. MCQ progress only appears for students with sharing ON.
        </p>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">Student</th>
              <th className="px-4 py-3">MCQ sharing</th>
              <th className="px-4 py-3">Chapter summaries</th>
              <th className="px-4 py-3">Consent updated</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-slate-200 dark:border-slate-800"><td colSpan={5} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td></tr>
              ))}
            {!isLoading && isError && (
              <tr><td colSpan={5} className="px-4 py-6"><InlineError error={error} title="Couldn’t load students" /></td></tr>
            )}
            {!isLoading && !isError && students.map((s) => (
              <tr key={s.studentId} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="px-4 py-3 font-mono font-medium text-slate-800 dark:text-slate-100">{s.studentId}</td>
                <td className="px-4 py-3">
                  {s.sharing ? (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-600"><ShieldCheck className="w-3.5 h-3.5" /> On</span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-400"><ShieldOff className="w-3.5 h-3.5" /> {s.sharing === null ? 'No record' : 'Off'}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{s.summaryCount}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{s.consentUpdatedAt ? new Date(s.consentUpdatedAt).toLocaleString() : '—'}</td>
                <td className="px-4 py-3">
                  <Link to={`/analytics/students/${s.studentId}`} className="inline-flex items-center gap-1 text-xs font-semibold text-[#2563EB] hover:underline">
                    Analysis <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </td>
              </tr>
            ))}
            {!isLoading && !isError && students.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500">No analytics students yet — student devices sync after enabling sharing.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
