// AI Content → Review Queue. Filters + paginated question list so the
// full chapter bank (~4,700 MCQs) is browsable. Click opens Question Review.
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Filter } from 'lucide-react';
import { useChapters, useReviewQueue } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { StatusBadge, DifficultyBadge, TypeBadge } from '@/components/content/ContentBadges';
import { cn } from '@/utils/format';

const SUBJECTS = ['Accounts', 'Law', 'Taxation', 'Costing', 'Audit', 'FM', 'SM'];
const DIFFICULTIES = ['easy', 'moderate', 'hard'];
const STATUSES = ['needs_review', 'changes_requested', 'rejected', 'approved', 'release_candidate', 'published'];
const TYPES = ['mcq', 'scenario_mcq'];
const PAGE_SIZES = [50, 100, 200];

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
        {options.map((o) => <option key={o.value || o} value={o.value || o}>{o.label || o}</option>)}
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
  const [status, setStatus] = useState('');
  const [hasWarnings, setHasWarnings] = useState('');
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);

  const { data: chaptersData } = useChapters();
  const chapterOptions = useMemo(() => {
    const items = chaptersData?.items || [];
    return items
      .filter((c) => !subject || c.subject === subject)
      .map((c) => ({
        value: c.chapterId,
        label: `${c.chapterId} — ${c.chapterTitle || ''}`.trim(),
      }));
  }, [chaptersData, subject]);

  useEffect(() => { setPage(1); }, [subject, chapterId, questionType, difficulty, status, hasWarnings, pageSize]);

  const params = useMemo(
    () => ({
      subject,
      chapterId,
      questionType,
      difficulty,
      status,
      hasWarnings: hasWarnings === '' ? undefined : hasWarnings === 'true',
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [subject, chapterId, questionType, difficulty, status, hasWarnings, pageSize, page]
  );
  const { data, isLoading, isError, error } = useReviewQueue(params);

  const total = data?.total ?? 0;
  const items = data?.items || [];
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const importedChapters = chaptersData?.items?.length || 0;

  const go = (next) => setPage(Math.min(pageCount, Math.max(1, next)));

  return (
    <div className="space-y-4" data-testid="review-queue">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Review Queue</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Full chapter MCQ bank. Reviewing is required before anything can be published.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 font-semibold">
            {total.toLocaleString()} questions
          </span>
          <span className="px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 font-semibold">
            {importedChapters} chapters
          </span>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-end gap-3">
        <Filter className="w-4 h-4 text-slate-400 mb-2" />
        <Select label="Subject" value={subject} onChange={(v) => { setSubject(v); setChapterId(''); }} options={SUBJECTS} />
        <Select label="Chapter" value={chapterId} onChange={setChapterId} options={chapterOptions} all="All chapters" />
        <Select label="Question type" value={questionType} onChange={setQuestionType} options={TYPES} />
        <Select label="Difficulty" value={difficulty} onChange={setDifficulty} options={DIFFICULTIES} />
        <Select label="Status" value={status} onChange={setStatus} options={STATUSES} />
        <Select label="Warnings" value={hasWarnings} onChange={setHasWarnings} options={['true', 'false']} all="Any" />
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">Per page</span>
          <select
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs text-slate-700 dark:text-slate-200"
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
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
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-200 dark:border-slate-800">
                    <td className="px-4 py-3" colSpan={7}><Skeleton className="h-5 w-full" /></td>
                  </tr>
                ))
              : items.map((q) => (
                  <tr
                    key={q.id}
                    className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer"
                    onClick={() => navigate(`/ai-content/questions?id=${q.id}`)}
                  >
                    <td className="px-4 py-3 max-w-[380px]">
                      <div className="font-medium text-slate-800 dark:text-slate-100 line-clamp-2">{q.prompt}</div>
                      <div className="font-mono text-[11px] text-slate-400">{q.id}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">
                      <div>{q.chapterId}</div>
                      {q.chapterTitle && <div className="text-[11px] text-slate-400 line-clamp-1">{q.chapterTitle}</div>}
                    </td>
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
            {!isLoading && items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500">No questions match the filters.</td></tr>
            )}
          </tbody>
        </table>

        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40" data-testid="queue-pagination">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {total === 0 ? 'No questions' : `Showing ${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`}
          </p>
          <div className="flex items-center gap-1">
            <PageBtn label="First page" onClick={() => go(1)} disabled={page <= 1}><ChevronsLeft className="w-4 h-4" /></PageBtn>
            <PageBtn label="Previous page" onClick={() => go(page - 1)} disabled={page <= 1}><ChevronLeft className="w-4 h-4" /></PageBtn>
            <span className="px-3 text-xs font-semibold text-slate-600 dark:text-slate-300">Page {page} / {pageCount}</span>
            <PageBtn label="Next page" onClick={() => go(page + 1)} disabled={page >= pageCount}><ChevronRight className="w-4 h-4" /></PageBtn>
            <PageBtn label="Last page" onClick={() => go(pageCount)} disabled={page >= pageCount}><ChevronsRight className="w-4 h-4" /></PageBtn>
          </div>
        </div>
      </div>
    </div>
  );
}

function PageBtn({ children, onClick, disabled, label }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="h-8 w-8 inline-flex items-center justify-center rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white dark:hover:bg-slate-800"
    >
      {children}
    </button>
  );
}
