// Analytics → Student-level analysis view (docs §8.4):
// profile, group, attempt, study activity (from existing Apps Script data),
// subject performance, chapter mastery, weak concepts, improvement trend,
// recommended next action, last activity, mentor notes / follow-ups.
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Lightbulb, ShieldCheck, ShieldOff, TrendingDown, TrendingUp } from 'lucide-react';
import { useStudent } from '@/api/hooks';
import { useStudentAnalysis } from '@/api/hooks-content';
import { BandBadge } from '@/components/content/ContentBadges';
import { Skeleton } from '@/components/common/Skeleton';
import InlineError from '@/components/common/InlineError';
import { StatusBadge as ProfileStatusBadge } from '@/components/common/RiskBadge';

export default function StudentAnalysisDetail() {
  const { id } = useParams();
  const { data: analysis, isLoading, isError, error } = useStudentAnalysis(id);
  // Existing backend profile (Apps Script) — study activity, group, attempt.
  const { data: profile } = useStudent(id);

  return (
    <div className="space-y-5" data-testid="student-analysis-detail">
      <div>
        <Link to="/analytics/students" className="inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-[#2563EB] mb-1">
          <ArrowLeft className="w-4 h-4" /> All students
        </Link>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Student Analysis — {id}</h2>
      </div>

      {isLoading && <Skeleton className="h-64 w-full" />}

      {!isLoading && isError && <InlineError error={error} title="Couldn’t load this student’s analysis" />}

      {analysis && (
        <>
          {/* Profile / consent / signals */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Profile</div>
              <div className="text-sm space-y-1 text-slate-700 dark:text-slate-200">
                <div><span className="text-slate-400">Group:</span> {profile?.group || '— (existing backend)'}</div>
                <div><span className="text-slate-400">Attempt:</span> {profile?.attempt || '— (existing backend)'}</div>
                <div><span className="text-slate-400">Status:</span> {profile ? <ProfileStatusBadge status={profile.status} /> : '—'}</div>
              </div>
              <div className="mt-3">
                {analysis.sharing ? (
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-600"><ShieldCheck className="w-3.5 h-3.5" /> MCQ sharing ON</span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-400"><ShieldOff className="w-3.5 h-3.5" /> MCQ sharing OFF — chapter mastery hidden</span>
                )}
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Activity</div>
              <div className="text-sm text-slate-700 dark:text-slate-200 space-y-1">
                <div><span className="text-slate-400">Study hours (7d):</span> {profile?.studyHours ?? '—'}</div>
                <div><span className="text-slate-400">Attendance:</span> {profile?.attendance ? `${profile.attendance}%` : '—'}</div>
                <div><span className="text-slate-400">MCQ accuracy (existing aggregate):</span> {profile?.mcqAccuracy ? `${profile.mcqAccuracy}%` : '—'}</div>
                <div><span className="text-slate-400">Last MCQ activity:</span> {analysis.lastActivity || '—'}</div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Recommended next action</div>
              <div className="space-y-2">
                {(analysis.recommendations || []).map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
                    <Lightbulb className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" /> {r}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Subject performance + trends */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Improvement tracking</div>
              {analysis.improvingChapters?.length > 0 && (
                <div className="flex items-start gap-2 text-sm text-emerald-600 mb-1.5">
                  <TrendingUp className="w-4 h-4 mt-0.5" /> Improving: {analysis.improvingChapters.join(', ')}
                </div>
              )}
              {analysis.decliningChapters?.length > 0 && (
                <div className="flex items-start gap-2 text-sm text-rose-600">
                  <TrendingDown className="w-4 h-4 mt-0.5" /> Declining: {analysis.decliningChapters.join(', ')}
                </div>
              )}
              {!analysis.improvingChapters?.length && !analysis.decliningChapters?.length && (
                <p className="text-sm text-slate-500">Not enough weekly snapshots for a trend yet.</p>
              )}
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-1.5">Weak concepts</div>
                <div className="flex flex-wrap gap-1.5">
                  {(analysis.weakConcepts || []).map((t) => (
                    <span key={t} className="px-2 py-0.5 rounded-md bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-100 dark:border-rose-900/50 text-[11px] font-medium">{t}</span>
                  ))}
                  {(analysis.weakConcepts || []).length === 0 && <span className="text-xs text-slate-400">None flagged</span>}
                </div>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Chapter mastery</div>
              {analysis.sharing && (analysis.summaries || []).length > 0 ? (
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {analysis.summaries.map((s) => (
                    <div key={s.chapterId} className="flex items-center justify-between gap-2 text-xs border-b border-slate-100 dark:border-slate-800 py-1.5 last:border-0">
                      <span className="font-mono text-slate-600 dark:text-slate-300">{s.chapterId}</span>
                      <span className="text-slate-400">{s.attemptCount} attempts · {s.accuracyRange}%</span>
                      <BandBadge band={s.masteryBand} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">Sharing disabled — device-local mastery is not visible to mentors.</p>
              )}
            </div>
          </div>

          {/* Follow-ups */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 mb-2">Mentor notes & follow-up status</div>
            {(analysis.followups || []).length === 0 && <p className="text-sm text-slate-500">No follow-up actions recorded for this student.</p>}
            <div className="space-y-2">
              {(analysis.followups || []).map((f) => (
                <div key={f.followupId} className="text-sm border border-slate-200 dark:border-slate-800 rounded-lg p-3">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-800 dark:text-slate-100">{f.title}</span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${f.status === 'completed' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                      {f.status}
                    </span>
                    <span className="ml-auto text-xs text-slate-400">{f.priority}</span>
                  </div>
                  {(f.notes || []).map((n, i) => (
                    <p key={i} className="text-xs text-slate-500 mt-1.5">“{n.note}” — {n.by}, {new Date(n.at).toLocaleString()}</p>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
