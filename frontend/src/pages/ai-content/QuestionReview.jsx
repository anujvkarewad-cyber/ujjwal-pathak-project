// AI Content → Question Review. Single-question deep review with validation,
// references and approval actions. Also renders the parent scenario passage
// when the question belongs to a scenario block.
import { useSearchParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useQuestion, useScenario, useValidationDetail } from '@/api/hooks-content';
import QuestionCard, { QuestionCardSkeleton } from '@/components/content/QuestionCard';
import { StatusBadge } from '@/components/content/ContentBadges';
import { Skeleton } from '@/components/common/Skeleton';

export default function QuestionReview() {
  const [params] = useSearchParams();
  const id = params.get('id') || '';
  const { data: question, isLoading } = useQuestion(id);
  const { data: validation } = useValidationDetail(id);
  const scenarioId = question?.scenario?.scenarioId;
  const { data: scenario } = useScenario(scenarioId);

  return (
    <div className="space-y-4" data-testid="question-review">
      <div>
        <Link to="/ai-content/queue" className="inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-[#2563EB] mb-1">
          <ArrowLeft className="w-4 h-4" /> Back to queue
        </Link>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Question Review</h2>
        {question && <div className="flex items-center gap-2 mt-1"><StatusBadge status={question.status} /><span className="text-xs text-slate-500">{question.chapterTitle} · {question.chapterId}</span></div>}
      </div>

      {!id && <p className="text-sm text-slate-500">Select a question from the Review Queue.</p>}
      {isLoading && <QuestionCardSkeleton />}
      {question && (
        <>
          {scenario && (
            <div className="bg-violet-50/70 dark:bg-violet-500/10 border border-violet-100 dark:border-violet-900/50 rounded-xl p-4">
              <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-violet-600 dark:text-violet-300 mb-1.5">
                Shared scenario passage · {scenario.scenarioId}
              </div>
              <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed">{scenario.passage}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {scenario.questionIds.map((qid, i) => (
                  <Link
                    key={qid}
                    to={`/ai-content/questions?id=${qid}`}
                    className={`px-2 py-0.5 rounded-md text-[11px] font-semibold border ${
                      qid === id
                        ? 'bg-violet-600 text-white border-violet-600'
                        : 'bg-white dark:bg-slate-900 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800 hover:bg-violet-50'
                    }`}
                  >
                    Q{i + 1}
                  </Link>
                ))}
              </div>
            </div>
          )}
          <QuestionCard question={question} />
          {validation && (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 text-xs text-slate-500 dark:text-slate-400">
              <span className="font-semibold">Status history:</span>{' '}
              {(validation.statusHistory || []).map((h, i) => (
                <span key={i}>
                  {i > 0 ? ' → ' : ''}
                  {h.to} <span className="text-slate-400">({h.by})</span>
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
