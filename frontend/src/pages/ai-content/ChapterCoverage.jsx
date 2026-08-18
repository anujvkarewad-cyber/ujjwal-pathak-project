// AI Content → Chapter Coverage. The 94-chapter gate matrix: 30 plain / 5
// scenarios / 20 linked MCQs per chapter, publishable state, gate drill-down.
// Plus one-click bulk actions: approve & publish a single chapter, a whole
// subject, or the entire bank in one shot.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Layers, Lock, PlayCircle, RefreshCw, Rocket, RocketIcon, Zap } from 'lucide-react';
import { toast } from 'sonner';
import {
  useApproveChapter,
  useBulkApproveAll,
  useBulkApproveChapter,
  useBulkApproveSubject,
  useChapters,
  useChapterGate,
  usePublishChapter,
} from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { Button } from '@/components/ui/button';
import { cn } from '@/utils/format';

const TARGETS = { plain: 30, scenarios: 5, scenarioMcqs: 20 };

function Counter({ label, have, target }) {
  const done = (have || 0) >= target;
  return (
    <div className={cn('flex items-center gap-2 text-xs', done ? 'text-emerald-600' : 'text-slate-500')}>
      <span className={cn('font-bold', done ? 'text-emerald-600' : 'text-slate-700 dark:text-slate-200')}>{have ?? 0}/{target}</span>
      <span className="text-[11px] uppercase tracking-wider">{label}</span>
      {done && <CheckCircle2 className="w-3.5 h-3.5" />}
    </div>
  );
}

function statusTone(status, publishable) {
  if (status === 'published') return { label: 'published', className: 'bg-blue-50 text-blue-700 border-blue-200' };
  if (status === 'release_candidate') return { label: 'release candidate', className: 'bg-violet-50 text-violet-700 border-violet-200' };
  if (publishable) return { label: 'publishable', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' };
  return { label: 'in review', className: 'bg-amber-50 text-amber-700 border-amber-200' };
}

function GatePanel({ chapterId, chapterStatus, onClose }) {
  const panelRef = useRef(null);
  const { data: gate, isLoading, isError, error, refetch, isFetching } = useChapterGate(chapterId);
  const approve = useApproveChapter();
  const publish = usePublishChapter();

  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [chapterId]);

  const busy = approve.isPending || publish.isPending;
  const coverage = gate?.coverage || {};
  const status = gate?.chapterStatus || chapterStatus || 'needs_review';
  const alreadyPublished = status === 'published';
  const releaseReady = status === 'release_candidate' || alreadyPublished;

  const onApprove = () => {
    approve.mutate(chapterId, {
      onSuccess: () => toast.success('Chapter approved as a release candidate. Click Publish to ship it to students.'),
      onError: (e) => toast.error(e.message || 'Could not approve chapter'),
    });
  };

  const onPublish = () => {
    publish.mutate(chapterId, {
      onSuccess: (res) => toast.success(`Chapter published${res?.revision ? ` as revision ${res.revision}` : ''}. Students can now download it.`),
      onError: (e) => toast.error(e.message || 'Could not publish chapter'),
    });
  };

  return (
    <div ref={panelRef} className="bg-slate-50 dark:bg-slate-800/40 border-t border-slate-200 dark:border-slate-800 p-5 space-y-3" data-testid="gate-panel">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">
          Publish gate — {gate?.chapterTitle || chapterId}
        </h3>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>Close</Button>
      </div>

      {isLoading && <Skeleton className="h-28 w-full" />}

      {isError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-900/50 p-3 space-y-2">
          <p className="text-xs font-semibold text-rose-700 dark:text-rose-300 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> Could not load the chapter gate
          </p>
          <p className="text-xs text-rose-600 dark:text-rose-400 whitespace-pre-wrap break-words">{error?.message || 'Unknown error'}</p>
          <Button type="button" size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={cn('w-3.5 h-3.5 mr-1', isFetching && 'animate-spin')} /> Retry
          </Button>
        </div>
      )}

      {!isLoading && !isError && gate && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Counter label="plain MCQs" have={coverage.plainApproved} target={coverage.plainTarget || TARGETS.plain} />
            <Counter label="scenarios" have={coverage.scenariosApproved} target={coverage.scenariosTarget || TARGETS.scenarios} />
            <Counter label="scenario MCQs" have={coverage.scenarioMcqsApproved} target={coverage.scenarioMcqsTarget || TARGETS.scenarioMcqs} />
          </div>
          {gate.errors?.length > 0 && (
            <div className="space-y-1">
              {gate.errors.map((e, i) => (
                <div key={i} className="text-xs text-rose-600 bg-rose-50 dark:bg-rose-500/10 border border-rose-100 dark:border-rose-900/50 rounded-lg px-3 py-2">{e}</div>
              ))}
            </div>
          )}
          {gate.warnings?.length > 0 && (
            <div className="space-y-1">
              {gate.warnings.map((w, i) => (
                <div key={i} className="text-xs text-amber-700 bg-amber-50 dark:bg-amber-500/10 border border-amber-100 dark:border-amber-900/50 rounded-lg px-3 py-2">{w}</div>
              ))}
            </div>
          )}
          {gate.publishable ? (
            <>
              <p className="text-sm text-emerald-600 font-medium">
                {alreadyPublished
                  ? 'Chapter is published. Publishing again creates a new revision.'
                  : releaseReady
                    ? 'Chapter is a release candidate. Publish to ship it to students.'
                    : 'Chapter meets the publish gate.'}
              </p>
              <div className="flex flex-wrap gap-2">
                {!alreadyPublished && !releaseReady && (
                  <Button
                    type="button"
                    size="sm"
                    className="bg-emerald-600 hover:bg-emerald-700 text-white"
                    disabled={busy}
                    data-testid="gate-approve"
                    onClick={onApprove}
                  >
                    <PlayCircle className="w-3.5 h-3.5 mr-1" /> Approve chapter → release candidate
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  className="bg-[#2563EB] hover:bg-[#1d4ed8] text-white"
                  disabled={busy}
                  data-testid="gate-publish"
                  onClick={onPublish}
                >
                  <Rocket className="w-3.5 h-3.5 mr-1" /> {alreadyPublished ? 'Publish new revision' : 'Publish to students'}
                </Button>
              </div>
            </>
          ) : (
            <p className="text-xs text-slate-500 flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5" /> Approve all required items first. Publishing is blocked until every gate passes.
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default function ChapterCoverage() {
  const { data, isLoading } = useChapters();
  const [openChapter, setOpenChapter] = useState(null);

  const chapters = data?.items || [];

  const bulkChapter = useBulkApproveChapter();
  const bulkSubject = useBulkApproveSubject();
  const bulkAll = useBulkApproveAll();
  const [subject, setSubject] = useState('');
  const subjects = useMemo(
    () => Array.from(new Set(chapters.map((c) => c.subject).filter(Boolean))).sort(),
    [chapters],
  );

  const bulkBusy = bulkChapter.isPending || bulkSubject.isPending || bulkAll.isPending;

  const onBulkChapter = (chapter) => {
    if (!window.confirm(`Approve & publish EVERY question in "${chapter.chapterTitle}"? Students will see them immediately.`)) return;
    bulkChapter.mutate(chapter.chapterId, {
      onSuccess: (res) => toast.success(res?.message || `Chapter ${chapter.chapterId} published.`),
      onError: (e) => toast.error(e.message || 'Bulk publish failed'),
    });
  };

  const onBulkSubject = () => {
    if (!subject) return;
    if (!window.confirm(`Approve & publish EVERY question of subject "${subject}"? Students will see them immediately.`)) return;
    bulkSubject.mutate(subject, {
      onSuccess: (res) => toast.success(res?.message || `Subject ${subject} published.`),
      onError: (e) => toast.error(e.message || 'Bulk publish failed'),
    });
  };

  const onBulkAll = () => {
    if (!window.confirm('Approve & publish the ENTIRE question bank (all subjects, all chapters) in one shot? Students will see everything immediately.')) return;
    bulkAll.mutate(undefined, {
      onSuccess: (res) => toast.success(res?.message || 'Entire bank published.'),
      onError: (e) => toast.error(e.message || 'Bulk publish failed'),
    });
  };

  return (
    <div className="space-y-4" data-testid="chapter-coverage">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Chapter Coverage</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Publish gate per official ICAI chapter: {TARGETS.plain} plain MCQs + {TARGETS.scenarios} scenarios × 4 linked MCQs = 50 questions.
        </p>
      </div>

      {/* One-click bulk publish toolbar */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Quick publish</span>
        <select
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className="h-9 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 text-sm text-slate-800 dark:text-slate-100"
          data-testid="bulk-subject-select"
        >
          <option value="">Select subject…</option>
          {subjects.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-emerald-300 text-emerald-700 hover:bg-emerald-50"
          disabled={!subject || bulkBusy}
          data-testid="bulk-subject-btn"
          onClick={onBulkSubject}
        >
          <Layers className="w-3.5 h-3.5 mr-1" /> Approve subject & publish
        </Button>
        <Button
          type="button"
          size="sm"
          className="bg-emerald-600 hover:bg-emerald-700 text-white"
          disabled={bulkBusy}
          data-testid="bulk-all-btn"
          onClick={onBulkAll}
        >
          <Zap className={cn('w-3.5 h-3.5 mr-1', bulkBusy && 'animate-pulse')} /> Approve ALL & publish (whole bank)
        </Button>
        <span className="text-[11px] text-slate-400">
          Bulk publish approves every eligible question and ships it to students in one release. Questions with validation errors stay in review.
        </span>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">Chapter</th>
              <th className="px-4 py-3">Subject</th>
              <th className="px-4 py-3">Group</th>
              <th className="px-4 py-3">Plain</th>
              <th className="px-4 py-3">Scenarios</th>
              <th className="px-4 py-3">Scenario MCQs</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i} className="border-b border-slate-200 dark:border-slate-800"><td colSpan={8} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td></tr>
              ))}
            {!isLoading && chapters.map((c) => {
              const countsOk = (c.coverage?.plainApproved || 0) >= TARGETS.plain
                && (c.coverage?.scenariosApproved || 0) >= TARGETS.scenarios
                && (c.coverage?.scenarioMcqsApproved || 0) >= TARGETS.scenarioMcqs;
              const tone = statusTone(c.status, countsOk);
              const open = openChapter === c.chapterId;
              return (
                <Fragment key={c.chapterId}>
                  <tr className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800 dark:text-slate-100">{c.chapterTitle}</div>
                      <div className="font-mono text-[11px] text-slate-400">{c.chapterId}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{c.subject}</td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{c.group || '—'}</td>
                    <td className="px-4 py-3"><Counter label="" have={c.coverage?.plainApproved} target={TARGETS.plain} /></td>
                    <td className="px-4 py-3"><Counter label="" have={c.coverage?.scenariosApproved} target={TARGETS.scenarios} /></td>
                    <td className="px-4 py-3"><Counter label="" have={c.coverage?.scenarioMcqsApproved} target={TARGETS.scenarioMcqs} /></td>
                    <td className="px-4 py-3">
                      <span className={cn('px-2.5 py-0.5 rounded-full text-[11px] font-semibold border', tone.className)}>
                        {tone.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant={open ? 'default' : 'outline'}
                          data-testid={`gate-button-${c.chapterId}`}
                          onClick={() => setOpenChapter(open ? null : c.chapterId)}
                        >
                          Gate
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          className="bg-emerald-600 hover:bg-emerald-700 text-white"
                          disabled={bulkBusy}
                          data-testid={`bulk-chapter-btn-${c.chapterId}`}
                          onClick={() => onBulkChapter(c)}
                        >
                          <Zap className="w-3.5 h-3.5 mr-1" /> Approve & publish
                        </Button>
                      </div>
                    </td>
                  </tr>
                  {open && (
                    <tr className="border-b border-slate-200 dark:border-slate-800">
                      <td colSpan={8} className="p-0">
                        <GatePanel
                          chapterId={c.chapterId}
                          chapterStatus={c.status}
                          onClose={() => setOpenChapter(null)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {!isLoading && chapters.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-slate-500">No chapter records yet — run the content pipeline stage-10 to stage drafts.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
