// AI Content → Chapter Coverage. The 94-chapter gate matrix: 30 plain / 5
// scenarios / 20 linked MCQs per chapter, publishable state, gate drill-down.
import { useState } from 'react';
import { CheckCircle2, Lock, PlayCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useApproveChapter, useChapters, useChapterGate } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { Button } from '@/components/ui/button';
import { cn } from '@/utils/format';

const TARGETS = { plain: 30, scenarios: 5, scenarioMcqs: 20 };

function Counter({ label, have, target }) {
  const done = have >= target;
  return (
    <div className={cn('flex items-center gap-2 text-xs', done ? 'text-emerald-600' : 'text-slate-500')}>
      <span className={cn('font-bold', done ? 'text-emerald-600' : 'text-slate-700 dark:text-slate-200')}>{have}/{target}</span>
      <span className="text-[11px] uppercase tracking-wider">{label}</span>
      {done && <CheckCircle2 className="w-3.5 h-3.5" />}
    </div>
  );
}

function GatePanel({ chapterId, onClose }) {
  const { data: gate, isLoading } = useChapterGate(chapterId);
  const approve = useApproveChapter();
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-3" data-testid="gate-panel">
      <div className="flex items-center justify-between">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Publish gate — {chapterId}</h3>
        <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Counter label="plain MCQs" have={gate.coverage.plainApproved} target={gate.coverage.plainTarget} />
        <Counter label="scenarios" have={gate.coverage.scenariosApproved} target={gate.coverage.scenariosTarget} />
        <Counter label="scenario MCQs" have={gate.coverage.scenarioMcqsApproved} target={gate.coverage.scenarioMcqsTarget} />
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
          <p className="text-sm text-emerald-600 font-medium">Chapter meets the publish gate.</p>
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
            onClick={() => approve.mutate(chapterId, { onSuccess: () => toast.success('Chapter approved → release candidate. Run the pipeline publish stage to build bundles.'), onError: (e) => toast.error(e.message) })}
          >
            <PlayCircle className="w-3.5 h-3.5 mr-1" /> Approve chapter → release candidate
          </Button>
        </>
      ) : (
        <p className="text-xs text-slate-500 flex items-center gap-1.5"><Lock className="w-3.5 h-3.5" /> Approve all required items first. Publishing is blocked until every gate passes.</p>
      )}
    </div>
  );
}

export default function ChapterCoverage() {
  const { data, isLoading } = useChapters();
  const [openChapter, setOpenChapter] = useState(null);

  const chapters = data?.items || [];

  return (
    <div className="space-y-4" data-testid="chapter-coverage">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Chapter Coverage</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Publish gate per official ICAI chapter: {TARGETS.plain} plain MCQs + {TARGETS.scenarios} scenarios × 4 linked MCQs = 50 questions.
        </p>
      </div>

      {openChapter && <GatePanel chapterId={openChapter} onClose={() => setOpenChapter(null)} />}

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
              const done = c.coverage.plainApproved >= 30 && c.coverage.scenariosApproved >= 5 && c.coverage.scenarioMcqsApproved >= 20;
              return (
                <tr key={c.chapterId} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-800 dark:text-slate-100">{c.chapterTitle}</div>
                    <div className="font-mono text-[11px] text-slate-400">{c.chapterId}</div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{c.subject}</td>
                  <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">{c.group || '—'}</td>
                  <td className="px-4 py-3"><Counter label="" have={c.coverage.plainApproved} target={TARGETS.plain} /></td>
                  <td className="px-4 py-3"><Counter label="" have={c.coverage.scenariosApproved} target={TARGETS.scenarios} /></td>
                  <td className="px-4 py-3"><Counter label="" have={c.coverage.scenarioMcqsApproved} target={TARGETS.scenarioMcqs} /></td>
                  <td className="px-4 py-3">
                    <span className={cn('px-2.5 py-0.5 rounded-full text-[11px] font-semibold border', done ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200')}>
                      {done ? 'publishable' : 'in review'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Button size="sm" variant="outline" onClick={() => setOpenChapter(openChapter === c.chapterId ? null : c.chapterId)}>Gate</Button>
                  </td>
                </tr>
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
