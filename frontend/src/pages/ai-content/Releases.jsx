// AI Content → Approved Releases. Published revisions, hashes and chapter
// inventory per release. Publishing happens in the pipeline (stage-11);
// this screen is the audit-facing view of what students can download.
import { useState } from 'react';
import { ChevronDown, ChevronUp, PackageCheck } from 'lucide-react';
import { useReleases } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

function ReleaseRow({ release }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800/60 text-left"
        onClick={() => setOpen(!open)}
        data-testid={`release-row-${release.revision}`}
      >
        <PackageCheck className="w-4 h-4 text-emerald-600" />
        <span className="font-heading font-semibold text-slate-900 dark:text-white">Revision {release.revision}</span>
        <span className="text-xs text-slate-500">{new Date(release.publishedAt).toLocaleString()}</span>
        <span className="text-xs text-slate-500">by {release.publishedBy}</span>
        <span className="text-xs text-slate-500">{release.manifest?.chapters?.length || 0} chapters</span>
        <span className="ml-auto">{open ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}</span>
      </button>
      {open && (
        <div className="border-t border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/30 p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {(release.manifest?.chapters || []).map((c) => (
              <div key={c.chapterId} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold text-slate-700 dark:text-slate-200">{c.chapterId}</span>
                  <span className="text-slate-400">
                    {c.counts.plain} plain · {c.counts.scenarios} scenarios · {c.counts.scenarioMcqs} scenario MCQs
                  </span>
                </div>
                <div className="mt-1.5 font-mono text-[10px] text-slate-400 break-all">{c.contentHash}</div>
                <div className="mt-1 font-mono text-[10px] text-slate-400">
                  web: {c.chunkWeb}
                  <br />
                  mobile: {c.chunkMobile}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Releases() {
  const { data, isLoading } = useReleases();
  const releases = data?.items || [];

  return (
    <div className="space-y-4" data-testid="releases">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Approved Releases</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Only gated, approved content is ever published. Each revision carries per-chapter sha256 hashes so web and mobile can verify integrity.
        </p>
      </div>
      {isLoading && <Skeleton className="h-32 w-full" />}
      <div className="space-y-3">
        {releases.map((r) => <ReleaseRow key={r.revision} release={r} />)}
        {!isLoading && releases.length === 0 && (
          <p className={cn('text-sm text-slate-500 p-8 text-center')}>No releases yet — approve content, then run the pipeline publish stage.</p>
        )}
      </div>
    </div>
  );
}
