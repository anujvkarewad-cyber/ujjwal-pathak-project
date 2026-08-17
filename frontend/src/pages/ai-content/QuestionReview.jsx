// AI Content → Question Review. Single-question deep review with validation,
// references and approval actions. Also renders the parent scenario passage
// when the question belongs to a scenario block.
// NEW: Previous/Next navigation so approving doesn't send you back to Q1.

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ChevronLeft, ChevronRight, CheckCircle2 } from 'lucide-react';
import { useQuestion, useScenario, useValidationDetail } from '@/api/hooks-content';
import QuestionCard, { QuestionCardSkeleton } from '@/components/content/QuestionCard';
import { StatusBadge } from '@/components/content/ContentBadges';
import { Button } from '@/components/ui/button';

export default function QuestionReview() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const id = params.get('id') || '';
  const { data: question, isLoading } = useQuestion(id);
  const { data: validation } = useValidationDetail(id);
  const scenarioId = question?.scenario?.scenarioId;
  const { data: scenario } = useScenario(scenarioId);

  const [queueIds, setQueueIds] = useState(() => {
    try {
      const raw = sessionStorage.getItem('reviewQueueIds');
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  });
  const [queueIndex, setQueueIndex] = useState(() => {
    try {
      const raw = sessionStorage.getItem('reviewQueueIndex');
      return raw !== null ? Number(raw) : -1;
    } catch { return -1; }
  });
  const [queueTotal, setQueueTotal] = useState(() => {
    try {
      const raw = sessionStorage.getItem('reviewQueueTotal');
      return raw ? Number(raw) : 0;
    } catch { return 0; }
  });
  const [autoNext, setAutoNext] = useState(() => {
    try {
      return localStorage.getItem('reviewAutoNext') === '1';
    } catch { return true; }
  });

  // Update index when id changes and queueIds available
  useEffect(() => {
    if (!id || queueIds.length === 0) return;
    const idx = queueIds.indexOf(id);
    if (idx !== -1 && idx !== queueIndex) {
      setQueueIndex(idx);
      try { sessionStorage.setItem('reviewQueueIndex', String(idx)); } catch {}
    }
  }, [id, queueIds]);

  // Load queue from sessionStorage on mount (in case user refreshed)
  useEffect(() => {
    try {
      const rawIds = sessionStorage.getItem('reviewQueueIds');
      const rawIdx = sessionStorage.getItem('reviewQueueIndex');
      const rawTotal = sessionStorage.getItem('reviewQueueTotal');
      if (rawIds) setQueueIds(JSON.parse(rawIds));
      if (rawIdx !== null) setQueueIndex(Number(rawIdx));
      if (rawTotal) setQueueTotal(Number(rawTotal));
    } catch {}
  }, []);

  useEffect(() => {
    try { localStorage.setItem('reviewAutoNext', autoNext ? '1' : '0'); } catch {}
  }, [autoNext]);

  // Keyboard shortcuts: ← → navigate, Esc back to queue
  useEffect(() => {
    const handler = (e) => {
      if (e.target && (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT' || e.target.isContentEditable)) return;
      if (e.key === 'ArrowLeft' && prevId) {
        e.preventDefault();
        goPrev();
      } else if (e.key === 'ArrowRight' && nextId) {
        e.preventDefault();
        goNext();
      } else if (e.key === 'Escape') {
        navigate('/ai-content/queue');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  });

  const prevId = useMemo(() => {
    if (queueIds.length === 0 || queueIndex <= 0) return null;
    return queueIds[queueIndex - 1] || null;
  }, [queueIds, queueIndex]);

  const nextId = useMemo(() => {
    if (queueIds.length === 0) return null;
    if (queueIndex === -1) return null;
    if (queueIndex >= queueIds.length - 1) return null;
    return queueIds[queueIndex + 1] || null;
  }, [queueIds, queueIndex]);

  const goPrev = () => {
    if (!prevId) return;
    try { sessionStorage.setItem('reviewQueueIndex', String(queueIndex - 1)); } catch {}
    navigate(`/ai-content/questions?id=${prevId}`);
  };

  const goNext = () => {
    if (!nextId) return;
    try { sessionStorage.setItem('reviewQueueIndex', String(queueIndex + 1)); } catch {}
    navigate(`/ai-content/questions?id=${nextId}`);
  };

  // When question is approved, auto-next if enabled
  const handleApproved = () => {
    if (autoNext && nextId) {
      setTimeout(() => goNext(), 400); // small delay to let toast show
    }
  };

  const progressText = queueIds.length > 0 && queueIndex >= 0
    ? `Question ${queueIndex + 1} of ${queueTotal || queueIds.length}`
    : null;

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

          {/* Prev / Next buttons */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={goPrev}
              disabled={!prevId}
              className="gap-1"
              title="Previous question (← arrow)"
            >
              <ChevronLeft className="w-4 h-4" /> Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={goNext}
              disabled={!nextId}
              className="gap-1"
              title="Next question (→ arrow)"
            >
              Next <ChevronRight className="w-4 h-4" />
            </Button>
            {nextId && (
              <span className="text-[11px] text-slate-400 hidden md:inline">→ auto after approve if checked</span>
            )}
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
                    onClick={() => {
                      try {
                        const idx = queueIds.indexOf(qid);
                        if (idx !== -1) sessionStorage.setItem('reviewQueueIndex', String(idx));
                      } catch {}
                    }}
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
          {/* Pass onApproved to auto-next */}
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

          {/* Bottom Prev/Next duplicate for convenience after long card */}
          <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
            <Button size="sm" variant="ghost" onClick={() => navigate('/ai-content/queue')} className="gap-1">
              <ArrowLeft className="w-4 h-4" /> Back to queue (Esc)
            </Button>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={goPrev} disabled={!prevId} className="gap-1">
                <ChevronLeft className="w-4 h-4" /> Previous (←)
              </Button>
              <Button size="sm" className="bg-[#2563EB] hover:bg-[#1d4ed8] text-white gap-1" onClick={goNext} disabled={!nextId}>
                {autoNext ? <><CheckCircle2 className="w-4 h-4" /> Approve & Next</> : <>Next <ChevronRight className="w-4 h-4" /></>}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
