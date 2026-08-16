// AI Content → Review Queue. Filters + question list; click opens Question Review.
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, Filter } from 'lucide-react';
import { useReviewQueue } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { StatusBadge, DifficultyBadge, TypeBadge } from '@/components/content/ContentBadges';
import { cn } from '@/utils/format';

const SUBJECTS = ['Accounting', 'Law', 'Costing', 'Audit', 'FM', 'SM', 'DT', 'GST'];
const DIFFICULTIES = ['easy', 'moderate', 'hard'];
const STATUSES = ['needs_review', 'changes_requested', 'rejected', 'approved', 'release_candidate', 'published'];
const TYPES = ['mcq', 'scenario_mcq'];

function Select({ label, value, onChange, options, all = 'All' }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">{label}</span>
      <select
        className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-700 dark:text-slate-200"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{all}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

export default function ReviewQueue() {
  const navigate = useNavigate();
  const [subject, setSubject] = useState('');
  const [chapterId, setChapterId] = useState('');
  const [questionType, setQuestionType] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [status, setStatus] = useState('needs_review');
  const [hasWarnings, setHasWarnings] = useState('');

  const params = useMemo(
    () => ({ subject, chapterId, questionType, difficulty, status, hasWarnings: hasWarnings === '' ? undefined : hasWarnings === 'true', limit: 200 }),
    [subject, chapterId, questionType, difficulty, status, hasWarnings]
  );
  const { data, isLoading, isError, error } = useReviewQueue(params);

  return (
    <div className="space-y-4" data-testid="review-queue">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Review Queue</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">AI-generated questions awaiting mentor review. Reviewing is required before anything can be published.</p>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-end gap-3">
        <Filter className="w-4 h-4 text-slate-400 mb-2" />
        <Select label="Subject" value={subject} onChange={setSubject} options={SUBJECTS} />
        <Select label="Question type" value={questionType} onChange={setQuestionType} options={TYPES} />
        <Select label="Difficulty" value={difficulty} onChange={setDifficulty} options={DIFFICULTIES} />
        <Select label="Status" value={status} onChange={setStatus} options={STATUSES} />
        <Select label="Warnings" value={hasWarnings} onChange={setHasWarnings} options={['true', 'false']} all="Any" />
        <input
          className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs min-w-[180px]"
          placeholder="chapterId (e.g. ch-law-03)"
          value={chapterId}
          onChange={(e) => setChapterId(e.target.value)}
        />
        <span className="text-xs text-slate-500 dark:text-slate-400 pb-1.5 ml-auto">{data ? `${data.items.length} shown` : ''}</span>
      </div>

      {isError && <p className="text-sm text-rose-600">{error.message}</p>}

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left" data-testid="queue-table">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">Question</th>
              <th className="px-4 py-3">Chapter</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Difficulty</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Warnings</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-200 dark:border-slate-800">
                    <td className="px-4 py-3" colSpan={7}><Skeleton className="h-5 w-full" /></td>
                  </tr>
                ))
              : (data?.items || []).map((q) => (
                  <tr
                    key={q.id}
                    className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer"
                    onClick={() => navigate(`/ai-content/questions?id=${q.id}`)}
                  >
                    <td className="px-4 py-3 max-w-[380px]">
                      <div className="font-medium text-slate-800 dark:text-slate-100 line-clamp-2">{q.prompt}</div>
                      <div className="font-mono text-[11px] text-slate-400">{q.id}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{q.chapterId}</td>
                    <td className="px-4 py-3"><TypeBadge questionType={q.questionType} /></td>
                    <td className="px-4 py-3"><DifficultyBadge difficulty={q.difficulty} /></td>
                    <td className="px-4 py-3"><StatusBadge status={q.status} /></td>
                    <td className="px-4 py-3 text-xs">
                      <span className={cn('font-semibold', (q.validation?.warnings || []).length ? 'text-amber-600' : 'text-slate-400')}>
                        {(q.validation?.warnings || []).length}
                      </span>
                    </td>
                    <td className="px-4 py-3"><ChevronRight className="w-4 h-4 text-slate-300" /></td>
                  </tr>
                ))}
            {!isLoading && (data?.items || []).length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500">No questions match the filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
