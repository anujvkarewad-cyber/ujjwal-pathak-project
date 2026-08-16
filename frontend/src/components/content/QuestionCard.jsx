// Question editor + review card: full prompt/options/answer/explanation with
// inline editing, ICAI + calibration refs, validation warnings, similarity,
// and approve/reject/request-changes actions.
import { useState } from 'react';
import { AlertTriangle, BookOpen, CheckCircle2, FlaskConical, MessageSquareWarning, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useDecideQuestion, useUpdateQuestion } from '@/api/hooks-content';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';
import { DifficultyBadge, StatusBadge, TypeBadge } from './ContentBadges';

const DIFFICULTIES = ['easy', 'moderate', 'hard'];
const OPTION_LETTERS = ['A', 'B', 'C', 'D'];

function RefBlock({ title, icon: Icon, refs }) {
  if (!refs || refs.length === 0) return null;
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400 mb-1.5">
        <Icon className="w-3.5 h-3.5" /> {title}
      </div>
      <div className="space-y-1">
        {refs.map((r, i) => (
          <div key={i} className="text-xs text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/60 rounded-md px-2.5 py-1.5 border border-slate-100 dark:border-slate-800">
            <span className="font-semibold">{r.source}</span>
            {r.attempt ? ` · ${r.attempt}` : ''}
            {r.module ? ` · ${r.module}` : ''}
            {r.chapter ? ` ch.${r.chapter}` : ''}
            {r.section ? ` · §${r.section}` : ''}
            {r.provision ? ` · ${r.provision}` : ''}
            {r.questionRef ? ` · ${r.questionRef}` : ''}
            {r.calibrationNote ? <div className="text-slate-500 dark:text-slate-400 mt-0.5">— {r.calibrationNote}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function QuestionCard({ question, readOnly = false }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(null);
  const [comment, setComment] = useState('');
  const updateQuestion = useUpdateQuestion();
  const decideQuestion = useDecideQuestion();

  const data = draft || question;
  const set = (patch) => setDraft((d) => ({ ...(d || question), ...patch }));

  const save = () => {
    const patch = {
      prompt: draft.prompt !== question.prompt ? draft.prompt : undefined,
      options: JSON.stringify(draft.options) !== JSON.stringify(question.options) ? draft.options : undefined,
      correctOptionId: draft.correctOptionId !== question.correctOptionId ? draft.correctOptionId : undefined,
      explanation: draft.explanation !== question.explanation ? draft.explanation : undefined,
      difficulty: draft.difficulty !== question.difficulty ? draft.difficulty : undefined,
      conceptTags: JSON.stringify(draft.conceptTags) !== JSON.stringify(question.conceptTags) ? draft.conceptTags : undefined,
    };
    updateQuestion.mutate(
      { id: question.id, patch },
      {
        onSuccess: (saved) => {
          setEditing(false);
          setDraft(saved);
          toast.success('Question updated and revalidated');
        },
        onError: (e) => toast.error(e.message),
      }
    );
  };

  const decide = (decision) => {
    decideQuestion.mutate(
      { id: question.id, decision, comment, warningsAcknowledged: false, attemptSpecificRiskConfirmed: false },
      {
        onSuccess: (saved) => toast.success(`Question ${decision.replace('_', ' ')}`),
        onError: (e) => toast.error(e.message),
      }
    );
  };

  const errors = data.validation?.errors || [];
  const warnings = data.validation?.warnings || [];
  const similarity = data.similarity || {};

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl" data-testid="question-card">
      <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500 dark:text-slate-400">{data.id}</span>
        <TypeBadge questionType={data.questionType} />
        <DifficultyBadge difficulty={data.difficulty} />
        <StatusBadge status={data.status} />
        {data.scenario && (
          <Badge variant="outline" className="text-[11px]">
            scenario · seq {data.scenario.seq}/{data.scenario.blockTotal}
          </Badge>
        )}
        {data.revision > 1 && <Badge variant="outline" className="text-[11px]">rev {data.revision}</Badge>}
        <div className="ml-auto flex items-center gap-2">
          {!readOnly && (
            <>
              {editing ? (
                <>
                  <Button size="sm" variant="outline" onClick={() => { setEditing(false); setDraft(null); }}>Cancel</Button>
                  <Button size="sm" onClick={save} disabled={updateQuestion.isPending}>Save</Button>
                </>
              ) : (
                <Button size="sm" variant="outline" onClick={() => { setEditing(true); setDraft(question); }}>Edit</Button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Prompt */}
        {editing ? (
          <textarea
            className="w-full min-h-[70px] rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-3 text-sm"
            value={data.prompt}
            onChange={(e) => set({ prompt: e.target.value })}
          />
        ) : (
          <p className="text-[15px] font-medium text-slate-900 dark:text-white leading-relaxed">{data.prompt}</p>
        )}

        {/* Options */}
        <div className="space-y-2">
          {data.options.map((o, i) => {
            const correct = o.id === data.correctOptionId;
            return (
              <div
                key={o.id}
                className={cn(
                  'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-sm',
                  correct
                    ? 'border-emerald-300 bg-emerald-50/60 dark:bg-emerald-500/10 dark:border-emerald-700'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40'
                )}
              >
                <span className={cn('font-bold w-5 shrink-0', correct ? 'text-emerald-600' : 'text-slate-500')}>{o.id}</span>
                {editing ? (
                  <div className="flex-1 space-y-1.5">
                    <textarea
                      className="w-full rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-2 text-sm"
                      value={o.text}
                      onChange={(e) => {
                        const options = data.options.map((x) => (x.id === o.id ? { ...x, text: e.target.value } : x));
                        set({ options });
                      }}
                    />
                    <button
                      type="button"
                      className={cn('text-[11px] font-semibold', correct ? 'text-emerald-600' : 'text-slate-400 hover:text-emerald-600')}
                      onClick={() => set({ correctOptionId: o.id })}
                    >
                      {correct ? '✓ correct answer' : `mark as correct (currently ${data.correctOptionId})`}
                    </button>
                  </div>
                ) : (
                  <span className="flex-1">{o.text}</span>
                )}
                {!editing && correct && <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />}
              </div>
            );
          })}
        </div>

        {/* Explanation */}
        {editing ? (
          <textarea
            className="w-full min-h-[80px] rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-3 text-sm"
            value={data.explanation}
            onChange={(e) => set({ explanation: e.target.value })}
          />
        ) : (
          <div className="text-sm text-slate-600 dark:text-slate-300 bg-blue-50/60 dark:bg-blue-500/10 border border-blue-100 dark:border-blue-900/50 rounded-lg p-3">
            <span className="font-semibold text-blue-700 dark:text-blue-300">Explanation: </span>
            {data.explanation}
          </div>
        )}

        {/* Concept tags + difficulty edit */}
        <div className="flex flex-wrap items-center gap-2">
          {(data.conceptTags || []).map((t) => (
            <span key={t} className="px-2 py-0.5 rounded-md bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-300 border border-violet-100 dark:border-violet-900/50 text-[11px] font-medium">
              {t}
            </span>
          ))}
          {editing && (
            <>
              <input
                className="flex-1 min-w-[160px] rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-xs"
                value={(data.conceptTags || []).join(', ')}
                placeholder="comma-separated tags"
                onChange={(e) => set({ conceptTags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })}
              />
              <select
                className="rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-xs"
                value={data.difficulty}
                onChange={(e) => set({ difficulty: e.target.value })}
              >
                {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </>
          )}
        </div>

        {/* Validation + similarity */}
        {(errors.length > 0 || warnings.length > 0) && (
          <div className="space-y-1.5">
            {errors.map((e, i) => (
              <div key={`e${i}`} className="flex items-start gap-2 text-xs text-rose-600 bg-rose-50 dark:bg-rose-500/10 border border-rose-100 dark:border-rose-900/50 rounded-lg px-3 py-2">
                <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {e}
              </div>
            ))}
            {warnings.map((w, i) => (
              <div key={`w${i}`} className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 dark:bg-amber-500/10 border border-amber-100 dark:border-amber-900/50 rounded-lg px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {w}
              </div>
            ))}
          </div>
        )}
        {similarity.verdict && (
          <div className={cn(
            'text-xs px-3 py-2 rounded-lg border',
            similarity.verdict === 'blocked' ? 'text-rose-600 bg-rose-50 border-rose-100 dark:border-rose-900/50' :
            similarity.verdict === 'flagged' ? 'text-amber-700 bg-amber-50 border-amber-100 dark:border-amber-900/50' :
            'text-slate-500 bg-slate-50 border-slate-100 dark:border-slate-800'
          )}>
            similarity: <span className="font-semibold">{similarity.verdict}</span>
            {' '}· source {Math.round((similarity.maxSourceSimilarity || 0) * 100)}% · bank {Math.round((similarity.maxBankSimilarity || 0) * 100)}%
          </div>
        )}
      </div>

      {/* Refs */}
      <div className="px-5 pb-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        <RefBlock title="ICAI source references" icon={BookOpen} refs={data.icaiSourceRefs} />
        <RefBlock title="RTP / MTP / PYQ calibration" icon={FlaskConical} refs={data.calibrationRefs} />
      </div>

      {/* Decision bar */}
      {!readOnly && !editing && (
        <div className="px-5 pb-5 border-t border-slate-200 dark:border-slate-800 pt-4 flex flex-wrap items-center gap-2">
          <input
            className="flex-1 min-w-[200px] rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs"
            placeholder="Comment (required for reject / request changes)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white" onClick={() => decide('approve')} disabled={decideQuestion.isPending}>
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Approve
          </Button>
          <Button size="sm" variant="outline" onClick={() => decide('request_changes')} disabled={!comment || decideQuestion.isPending}>
            <MessageSquareWarning className="w-3.5 h-3.5 mr-1" /> Request changes
          </Button>
          <Button size="sm" variant="outline" className="text-rose-600 border-rose-200 hover:bg-rose-50" onClick={() => decide('reject')} disabled={!comment || decideQuestion.isPending}>
            <XCircle className="w-3.5 h-3.5 mr-1" /> Reject
          </Button>
        </div>
      )}
    </div>
  );
}

export function QuestionCardSkeleton() {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-4">
      <Skeleton className="h-5 w-64" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}
