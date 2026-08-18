// Home-dashboard card: pending chapter MCQs with one-click approve.
//
// Fetches the LIVE backend directly (GET /api/content/stats and
// GET /api/content/queue) rather than going through any mock adapter, so this
// card always reflects the real generated chapter bank (~4,700 MCQs) and can
// never render DEMO content.
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BookOpenCheck, CheckCircle2, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { apiCall } from '@/api/backendClient';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/common/Skeleton';
import { DifficultyBadge, TypeBadge } from '@/components/content/ContentBadges';

export default function McqReviewPanel() {
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, q] = await Promise.all([
        apiCall('/api/content/stats'),
        apiCall('/api/content/queue', { params: { status: 'needs_review', view: 'summary', limit: 6 } }),
      ]);
      setStats(s);
      setItems(q?.items || []);
    } catch (e) {
      setStats(null);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const approve = async (id, event) => {
    event.stopPropagation();
    setApproving(true);
    try {
      await apiCall(`/api/content/questions/${id}/decision`, {
        method: 'POST',
        body: {
          decision: 'approve',
          comment: 'Approved from dashboard',
          warningsAcknowledged: true,
          attemptSpecificRiskConfirmed: true,
        },
      });
      toast.success('MCQ approved');
      await load();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setApproving(false);
    }
  };

  const bulkPublishAll = async () => {
    if (!window.confirm('Approve & publish the ENTIRE question bank (all subjects, all chapters) now? Students will see everything immediately.')) return;
    setBulkBusy(true);
    try {
      const res = await apiCall('/api/content/bulk-approve-publish-all', { method: 'POST', body: {} });
      toast.success(res?.message || 'Entire bank published.');
      await load();
    } catch (e) {
      toast.error(e.message || 'Bulk publish failed');
    } finally {
      setBulkBusy(false);
    }
  };

  const pending = stats?.needsReview ?? 0;
  const total = stats?.total ?? 0;
  const approved = stats?.approved ?? 0;

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl" data-testid="mcq-review-panel">
      <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-wrap items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 text-[#2563EB] flex items-center justify-center">
          <BookOpenCheck className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-heading font-semibold text-slate-900 dark:text-white">MCQ Review</h3>
            <span
              className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
              data-testid="live-bank-badge"
              title="Serving the live generated chapter bank (not demo data)"
            >
              Live Bank · V2
            </span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">Approve generated chapter questions before students practice them.</p>
        </div>
        <Link to="/ai-content/queue" className="ml-auto text-sm font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-1">
          Open full queue <ChevronRight className="w-4 h-4" />
        </Link>
      </div>

      {(pending > 0 || bulkBusy) && (
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 bg-emerald-50/60 dark:bg-emerald-500/5 flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
              {pending.toLocaleString()} questions awaiting approval
            </p>
            <p className="text-xs text-emerald-700/80 dark:text-emerald-400/80">
              One click: approve & publish everything (all subjects). Questions with validation errors stay in review.
            </p>
          </div>
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
            disabled={bulkBusy || approving}
            data-testid="bulk-publish-all"
            onClick={bulkPublishAll}
          >
            <Zap className="w-3.5 h-3.5 mr-1" /> {bulkBusy ? 'Publishing…' : 'Approve ALL & publish'}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-3 divide-x divide-slate-200 dark:divide-slate-800 border-b border-slate-200 dark:border-slate-800">
        <Stat label="In bank" value={loading ? '—' : total.toLocaleString()} />
        <Stat label="Awaiting approval" value={loading ? '—' : pending.toLocaleString()} accent />
        <Stat label="Approved" value={loading ? '—' : approved.toLocaleString()} />
      </div>

      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {loading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="p-4"><Skeleton className="h-10 w-full" /></div>
        ))}
        {!loading && items.map((q) => (
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
              disabled={approving}
              onClick={(e) => approve(q.id, e)}
            >
              <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Approve
            </Button>
          </div>
        ))}
        {!loading && items.length === 0 && (
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
