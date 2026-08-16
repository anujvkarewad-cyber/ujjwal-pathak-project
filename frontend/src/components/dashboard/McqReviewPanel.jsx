// Home-dashboard card: pending chapter MCQs with one-click approve.
import { Link, useNavigate } from 'react-router-dom';
import { BookOpenCheck, CheckCircle2, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { useContentStats, useDecideQuestion, useReviewQueue } from '@/api/hooks-content';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/common/Skeleton';
import { DifficultyBadge, TypeBadge } from '@/components/content/ContentBadges';

export default function McqReviewPanel() {
  const navigate = useNavigate();
  const { data: stats, isLoading: statsLoading } = useContentStats();
  const { data: queue, isLoading: queueLoading } = useReviewQueue({ status: 'needs_review', limit: 6 });
  const decide = useDecideQuestion();

  const pending = stats?.needsReview ?? 0;
  const total = stats?.total ?? 0;
  const approved = stats?.approved ?? 0;
  const items = queue?.items || [];

  const approve = (id, event) => {
    event.stopPropagation();
    decide.mutate(
      { id, decision: 'approve', comment: 'Approved from dashboard', warningsAcknowledged: true, attemptSpecificRiskConfirmed: true },
      {
        onSuccess: () => toast.success('MCQ approved'),
        onError: (e) => toast.error(e.message),
      }
    );
  };

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl" data-testid="mcq-review-panel">
      <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-[#2563EB] flex items-center justify-center">
          <BookOpenCheck className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">MCQ Review</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">Approve generated chapter questions before students practice them.</p>
        </div>
        <Link to="/ai-content/queue" className="ml-auto text-sm font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-1">
          Open full queue <ChevronRight className="w-4 h-4" />
        </Link>
      </div>

      <div className="grid grid-cols-3 divide-x divide-slate-200 dark:divide-slate-800 border-b border-slate-200 dark:border-slate-800">
        <Stat label="In bank" value={statsLoading ? '—' : total.toLocaleString()} />
        <Stat label="Awaiting approval" value={statsLoading ? '—' : pending.toLocaleString()} accent />
        <Stat label="Approved" value={statsLoading ? '—' : approved.toLocaleString()} />
      </div>

      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {queueLoading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="p-4"><Skeleton className="h-10 w-full" /></div>
        ))}
        {!queueLoading && items.map((q) => (
          <div
            key={q.id}
            className="p-4 flex flex-wrap items-start gap-3 hover:bg-slate-50/80 dark:hover:bg-slate-800/40 cursor-pointer"
            onClick={() => navigate(`/ai-content/questions?id=${q.id}`)}
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100 line-clamp-2">{q.prompt}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                <TypeBadge questionType={q.questionType} />
                <DifficultyBadge difficulty={q.difficulty} />
                <span className="font-mono">{q.chapterId}</span>
              </div>
            </div>
            <Button
              size="sm"
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
              disabled={decide.isPending}
              onClick={(e) => approve(q.id, e)}
            >
              <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Approve
            </Button>
          </div>
        ))}
        {!queueLoading && items.length === 0 && (
          <p className="p-6 text-sm text-slate-500 text-center">
            {total === 0 ? 'No chapter MCQs imported yet.' : 'No questions waiting for approval.'}
          </p>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="px-4 py-3">
      <div className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-500">{label}</div>
      <div className={`mt-0.5 font-heading text-xl font-bold ${accent ? 'text-amber-600' : 'text-slate-900 dark:text-white'}`}>{value}</div>
    </div>
  );
}
