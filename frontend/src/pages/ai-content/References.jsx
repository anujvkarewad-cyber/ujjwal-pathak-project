// AI Content → Calibration References. Browse every question's ICAI module
// refs and RTP/MTP/PYQ calibration refs, filter by source/attempt, jump to
// the question.
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { BookOpen, FlaskConical } from 'lucide-react';
import { useReviewQueue } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';

function Select({ label, value, onChange, options }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.16em] font-semibold text-slate-500 dark:text-slate-400">{label}</span>
      <select
        className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

export default function References() {
  const [source, setSource] = useState('');
  const [attempt, setAttempt] = useState('');
  const { data, isLoading } = useReviewQueue({ view: 'references', limit: 5000 });

  const rows = useMemo(() => {
    const out = [];
    for (const q of data?.items || []) {
      for (const r of q.icaiSourceRefs || []) out.push({ questionId: q.id, prompt: q.prompt, ref: r, kind: 'module' });
      for (const r of q.calibrationRefs || []) out.push({ questionId: q.id, prompt: q.prompt, ref: r, kind: 'calibration' });
    }
    return out.filter((row) => (!source || row.ref.source === source) && (!attempt || row.ref.attempt === attempt));
  }, [data, source, attempt]);

  const sources = useMemo(() => [...new Set((data?.items || []).flatMap((q) => (q.calibrationRefs || []).map((r) => r.source)))], [data]);
  const attempts = useMemo(() => [...new Set((data?.items || []).flatMap((q) => (q.calibrationRefs || []).map((r) => r.attempt).filter(Boolean)))], [data]);

  return (
    <div className="space-y-4" data-testid="references">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Calibration References</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">ICAI module source references and RTP/MTP/PYQ calibration benchmarks per question.</p>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-end gap-3">
        <Select label="Calibration source" value={source} onChange={setSource} options={sources} />
        <Select label="Attempt" value={attempt} onChange={setAttempt} options={attempts} />
        <span className="text-xs text-slate-500 pb-1.5 ml-auto">{rows.length} references</span>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-xs text-slate-500 uppercase bg-slate-50 dark:bg-slate-800/50 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <th className="px-4 py-3">Question</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Source</th>
              <th className="px-4 py-3">Attempt / Module / §</th>
              <th className="px-4 py-3">Note</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 4 }).map((_, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800"><td colSpan={5} className="px-4 py-3"><Skeleton className="h-5 w-full" /></td></tr>
            ))}
            {!isLoading && rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <td className="px-4 py-3 max-w-[420px]">
                  <div className="line-clamp-2 text-slate-800 dark:text-slate-100">{row.prompt}</div>
                  <Link to={`/ai-content/questions?id=${row.questionId}`} className="font-mono text-[11px] text-[#2563EB] hover:underline">{row.questionId}</Link>
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border bg-slate-50 border-slate-200 text-slate-600">
                    {row.kind === 'module' ? <BookOpen className="w-3 h-3" /> : <FlaskConical className="w-3 h-3" />}
                    {row.kind === 'module' ? 'ICAI module' : 'calibration'}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs font-semibold text-slate-700 dark:text-slate-200">{row.ref.source}</td>
                <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">
                  {[row.ref.attempt, row.ref.module, row.ref.section ? `§${row.ref.section}` : null, row.ref.provision, row.ref.questionRef].filter(Boolean).join(' · ') || '—'}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500 max-w-[220px]">{row.ref.calibrationNote || '—'}</td>
              </tr>
            ))}
            {!isLoading && rows.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500">No references match the filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
