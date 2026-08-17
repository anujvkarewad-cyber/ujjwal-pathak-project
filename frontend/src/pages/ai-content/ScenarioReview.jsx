// AI Content → Scenario Review. Whole-block review: one shared passage + its
// 4 linked questions; approve/reject applies to the entire block.
import { useState } from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useDecideScenario, useReviewQueue, useScenario } from '@/api/hooks-content';
import QuestionCard from '@/components/content/QuestionCard';
import { StatusBadge } from '@/components/content/ContentBadges';
import { Skeleton } from '@/components/common/Skeleton';
import { Button } from '@/components/ui/button';

function ScenarioBlock({ scenarioId }) {
  const { data: scenario, isLoading } = useScenario(scenarioId);
  const [comment, setComment] = useState('');
  const decideScenario = useDecideScenario();

  const decide = (decision) => {
    decideScenario.mutate(
      { id: scenarioId, decision, comment, warningsAcknowledged: true, attemptSpecificRiskConfirmed: true },)
      {
        onSuccess: () => toast.success(`Scenario block ${decision === 'approve' ? 'approved' : 'rejected'}`),
        onError: (e) => toast.error(e.message),
      }
    );
  };

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (!scenario) return <p className="text-sm text-slate-500">Scenario not found.</p>;

  return (
    <div className="space-y-4" data-testid="scenario-block">
      <div className="bg-violet-50/70 dark:bg-violet-500/10 border border-violet-100 dark:border-violet-900/50 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[11px] uppercase tracking-[0.16em] font-semibold text-violet-600 dark:text-violet-300">Shared passage · {scenario.scenarioId}</span>
          <StatusBadge status={scenario.status} />
        </div>
        <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed">{scenario.passage}</p>
        <p className="mt-2 text-xs text-slate-500 font-mono">{scenario.chapterId}</p>
      </div>
      {(scenario.questions || [])
        .sort((a, b) => (a.scenario?.seq || 0) - (b.scenario?.seq || 0))
        .map((q) => (
          <div key={q.id} className="space-y-1">
            <div className="text-[11px] uppercase tracking-[0.16em] font-semibold text-slate-400">Question {q.scenario?.seq} of 4</div>
            <QuestionCard question={q} />
          </div>
        ))}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-center gap-2">
        <input
          className="flex-1 min-w-[220px] rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs"
          placeholder="Comment (required for reject)"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white" onClick={() => decide('approve')} disabled={decideScenario.isPending}>
          <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Approve whole block
        </Button>
        <Button size="sm" variant="outline" className="text-rose-600 border-rose-200 hover:bg-rose-50" disabled={!comment || decideScenario.isPending} onClick={() => decide('reject')}>
          <XCircle className="w-3.5 h-3.5 mr-1" /> Reject whole block
        </Button>
      </div>
    </div>
  );
}

export default function ScenarioReview() {
  const { data, isLoading } = useReviewQueue({ questionType: 'scenario_mcq', limit: 5000 });
  const [openScenarioId, setOpenScenarioId] = useState(null);

  const groups = {};
  for (const q of data?.items || []) {
    const sid = q.scenario?.scenarioId;
    if (!sid) continue;
    groups[sid] = groups[sid] || { scenarioId: sid, status: q.status, chapterId: q.chapterId };
  }
  const scenarios = Object.values(groups).sort((a, b) => a.scenarioId.localeCompare(b.scenarioId));

  return (
    <div className="space-y-4" data-testid="scenario-review">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Scenario Review</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Each case scenario is one shared passage with 4 linked MCQs. Approve or reject the whole block — decisions are all-or-nothing.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-3 space-y-1 h-fit">
          <div className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-400 px-2 pb-1.5">{scenarios.length} scenario blocks</div>
          {isLoading && <Skeleton className="h-24 w-full" />}
          {!isLoading && scenarios.map((s) => (
            <button
              key={s.scenarioId}
              onClick={() => setOpenScenarioId(s.scenarioId === openScenarioId ? null : s.scenarioId)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                openScenarioId === s.scenarioId
                  ? 'bg-[#2563EB] text-white'
                  : 'text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/60'
              }`}
            >
              <div className="font-mono">{s.scenarioId}</div>
              <div className="flex items-center gap-1.5 mt-1">
                <StatusBadge status={s.status} className={openScenarioId === s.scenarioId ? 'bg-white/10 text-white border-white/30' : ''} />
              </div>
            </button>
          ))}
          {!isLoading && scenarios.length === 0 && <p className="px-2 py-4 text-xs text-slate-500">No scenario MCQs in the queue.</p>}
        </div>

        <div className="space-y-4">
          {openScenarioId && <ScenarioBlock scenarioId={openScenarioId} />}
          {!openScenarioId && <p className="text-sm text-slate-500 p-8 text-center">Select a scenario block to review its 4 linked questions together.</p>}
        </div>
      </div>
    </div>
  );
}
