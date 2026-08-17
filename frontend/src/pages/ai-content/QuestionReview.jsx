// AI Content → Question Review. Single-question deep review with validation,
// references and approval actions. Also renders the parent scenario passage
// when the question belongs to a scenario block.
//
// Previous / Next navigation works across queue pages: when you reach the end
// of the loaded page it fetches the next page with the same filters and keeps
// going. "Approve & Next" approves the current question and jumps straight to
// the next one — no more landing back on question 1.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ChevronLeft, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useQuestion, useScenario, useValidationDetail, useDecideQuestion } from '@/api/hooks-content';
import { listQueue } from '@/api/content';
import { loadQueueContext, saveQueueContext, queueFiltersToParams } from '@/utils/reviewQueueSession';
import QuestionCard, { QuestionCardSkeleton } from '@/components/content/QuestionCard';
import { StatusBadge } from '@/components/content/ContentBadges';
import { Button } from '@/components/ui/button';

const ACTIONABLE_STATUSES = ['needs_review', 'changes_requested', 'rejected'];

export default function QuestionReview() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const id = params.get('id') || '';
  const { data: question, isLoading } = useQuestion(id);
  const { data: validation } = useValidationDetail(id);
  const scenarioId = question?.scenario?.scenarioId;
  const { data: scenario } = useScenario(scenarioId);

  // Queue context saved when a row is clicked in Review Queue:
  // { ids, index, page, size, total, filters }
  const [ctx, setCtx] = useState(loadQueueContext);
  // 'prev' | 'next' while fetching an adjacent queue page (cross-page nav)
  const [loadingDir, setLoadingDir] = useState(null);
  const [autoNext, setAutoNext] = useState(() => {
    try { return localStorage.getItem('reviewAutoNext') !== '0'; } catch { return true; }
  });

  const decideQuestion = useDecideQuestion();

  useEffect(() => {
    try { localStorage.setItem('reviewAutoNext', autoNext ? '1' : '0'); } catch {}
  }, [autoNext]);

  // Keep the index in sync when the URL id changes (prev/next, scenario links)
  useEffect(() => {
    if (!id || ctx.ids.length === 0) return;
    const idx = ctx.ids.indexOf(id);
    if (idx !== -1 && idx !== ctx.index) {
      setCtx((c) => {
        const next = { ...c, index: idx };
        saveQueueContext(next);
        return next;
      });
    }
  }, [id, ctx.ids, ctx.index]);

  // Where are we in the whole queue (across pages)?
  const inQueue = ctx.ids.length > 0 && ctx.index >= 0;
  const position = inQueue ? (ctx.page - 1) * ctx.size + ctx.index + 1 : null;
  const totalAll = ctx.total || ctx.ids.length;
  const progressText = inQueue ? `Question ${position} of ${totalAll}` : null;

  const hasPrevInPage = inQueue && ctx.index > 0;
  const hasNextInPage = inQueue && ctx.index < ctx.ids.length - 1;
  const hasPrevPage = ctx.page > 1;
  const hasNextPage = ctx.total > 0 && ctx.page * ctx.size < ctx.total;
  const hasPrev = hasPrevInPage || hasPrevPage;
  const hasNext = hasNextInPage || hasNextPage;

  // Fetch the adjacent queue page with the same filters and swap it in as the
  // new navigation window. Returns the updated context.
  const fetchAdjacentPage = useCallback(async (direction) => {
    const page = direction === 'next' ? ctx.page + 1 : ctx.page - 1;
    const res = await listQueue(queueFiltersToParams(ctx.filters, ctx.size, (page - 1) * ctx.size));
    const items = res?.items || [];
    if (items.length === 0) throw new Error(`No questions found on page ${page} of the queue.`);
    const ids = items.map((q) => q.id);
    const nextCtx = {
      ...ctx,
      ids,
      page,
      total: res?.total ?? ctx.total,
      index: direction === 'next' ? 0 : ids.length - 1,
    };
    setCtx(nextCtx);
    saveQueueContext(nextCtx);
    return nextCtx;
  }, [ctx]);

  const goPrev = useCallback(async () => {
    if (!hasPrev || loadingDir) return;
    if (hasPrevInPage) {
      const next = { ...ctx, index: ctx.index - 1 };
      setCtx(next);
      saveQueueContext(next);
      navigate(`/ai-content/questions?id=${ctx.ids[ctx.index - 1]}`);
      return;
    }
    setLoadingDir('prev');
    try {
      const c = await fetchAdjacentPage('prev');
      navigate(`/ai-content/questions?id=${c.ids[c.index]}`);
    } catch (e) {
      toast.error(e.message || 'Could not load the previous page of the queue.');
    } finally {
      setLoadingDir(null);
    }
  }, [ctx, hasPrev, hasPrevInPage, loadingDir, navigate, fetchAdjacentPage]);

  const goNext = useCallback(async () => {
    if (!hasNext || loadingDir) return;
    if (hasNextInPage) {
      const next = { ...ctx, index: ctx.index + 1 };
      setCtx(next);
      saveQueueContext(next);
      navigate(`/ai-content/questions?id=${ctx.ids[ctx.index + 1]}`);
      return;
    }
    setLoadingDir('next');
    try {
      const c = await fetchAdjacentPage('next');
      navigate(`/ai-content/questions?id=${c.ids[c.index]}`);
    } catch (e) {
      toast.error(e.message || 'Could not load the next page of the queue.');
    } finally {
      setLoadingDir(null);
    }
  }, [ctx, hasNext, hasNextInPage, loadingDir, navigate, fetchAdjacentPage]);

  // Approve & Next: approve the current question, then jump to the next one.
  const approveAndNext = () => {
    if (!id || decideQuestion.isPending) return;
    decideQuestion.mutate(
      { id, decision: 'approve', comment: '', warningsAcknowledged: true, attemptSpecificRiskConfirmed: true },
      {
        onSuccess: () => {
          toast.success('Question approved');
          goNext();
        },
        onError: (e) => toast.error(e.message),
      }
    );
  };

  // Auto-next when the card's own Approve button is used
  const handleApproved = () => {
    if (autoNext) setTimeout(() => goNext(), 350); // brief pause so the toast is visible
  };

  // Keyboard shortcuts: ← → navigate, Esc back to queue
  useEffect(() => {
    const handler = (e) => {
      if (e.target && (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT' || e.target.isContentEditable)) return;
      if (e.key === 'ArrowLeft' && hasPrev) {
        e.preventDefault();
        goPrev();
      } else if (e.key === 'ArrowRight' && hasNext) {
        e.preventDefault();
        goNext();
      } else if (e.key === 'Escape') {
        navigate('/ai-content/queue');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [goPrev, goNext, hasPrev, hasNext, navigate]);

  const canApprove = !!question && ACTIONABLE_STATUSES.includes(question.status);

  const prevBtn = (withKeys) => (
    <Button
      size="sm"
      variant="outline"
      onClick={goPrev}
      disabled={!hasPrev || loadingDir === 'prev'}
      className="gap-1"
      title="Previous question (← arrow)"
    >
      {loadingDir === 'prev' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronLeft className="w-4 h-4" />}
      Previous{withKeys ? ' (←)' : ''}
    </Button>
  );

  const nextBtn = (withKeys) => (
    <Button
      size="sm"
      variant="outline"
      onClick={goNext}
      disabled={!hasNext || loadingDir === 'next'}
      className="gap-1"
      title="Next question (→ arrow)"
    >
      Next{withKeys ? ' (→)' : ''}
      {loadingDir === 'next' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
    </Button>
  );

  return (
    <div className="space-y-4" data-testid="question-review">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
          <Link to="/ai-content/queue" className="inline-flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-[#2563EB]">
            <ArrowLeft className="w-4 h-4" /> Back to queue
          </Link>
          <div className="flex items-center gap-2">
            {progressText && (
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2.5 py-1 rounded-full">
                {progressText}
              </span>
            )}
            <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400 cursor-pointer select-none">
              <input type="checkbox" checked={autoNext} onChange={(e) => setAutoNext(e.target.checked)} className="rounded border-slate-300" />
              Auto-next after approve
            </label>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Question Review</h2>
            {question && (
              <div className="flex items-center gap-2 mt-1">
                <StatusBadge status={question.status} />
                <span className="text-xs text-slate-500">{question.chapterTitle} · {question.chapterId}</span>
                <span className="text-xs font-mono text-slate-400">{question.id}</span>
              </div>
            )}
          </div>

          {/* Prev / Next — continue across queue pages automatically */}
          <div className="flex items-center gap-2">
            {prevBtn(false)}
            {nextBtn(false)}
          </div>
        </div>
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
          <QuestionCard question={question} onApproved={handleApproved} />

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

          {/* Bottom Prev / Approve & Next / Next for convenience after the long card */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
            <Button size="sm" variant="ghost" onClick={() => navigate('/ai-content/queue')} className="gap-1">
              <ArrowLeft className="w-4 h-4" /> Back to queue (Esc)
            </Button>
            <div className="flex items-center gap-2">
              {prevBtn(true)}
              {canApprove ? (
                <Button
                  size="sm"
                  className="bg-[#2563EB] hover:bg-[#1d4ed8] text-white gap-1"
                  onClick={approveAndNext}
                  disabled={!hasNext || decideQuestion.isPending || loadingDir === 'next'}
                  title="Approve this question and jump to the next one"
                >
                  {decideQuestion.isPending || loadingDir === 'next'
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <CheckCircle2 className="w-4 h-4" />}
                  Approve & Next
                </Button>
              ) : (
                nextBtn(true)
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
