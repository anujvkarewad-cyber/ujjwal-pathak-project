// Analytics → Chapter Mastery Heatmap.
// Rows = students, columns = official ICAI chapters, cell = mastery band.
// Hatching overlay marks "No recent activity" cells.
import { useMemo, useState } from 'react';
import { useHeatmap } from '@/api/hooks-content';
import { BAND_COLORS } from '@/components/content/ContentBadges';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const BANDS = ['Not assessed', 'Weak', 'Medium', 'Strong', 'Mastered'];

export default function Heatmap() {
  const [band, setBand] = useState('');
  const [chapterId, setChapterId] = useState('');
  const { data, isLoading } = useHeatmap({ band, chapterId });

  const cellMap = useMemo(() => {
    const m = {};
    for (const c of data?.cells || []) m[`${c.studentId}|${c.chapterId}`] = c;
    return m;
  }, [data]);

  const students = data?.students || [];
  const chapters = data?.chapters || [];

  return (
    <div className="space-y-4" data-testid="heatmap">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Chapter Mastery Heatmap</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Rows = students, columns = official ICAI chapters. Striped cells = no recent activity (14 days).</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
        <select className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs" value={band} onChange={(e) => setBand(e.target.value)}>
          <option value="">All bands</option>
          {BANDS.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <input
          className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-xs min-w-[180px]"
          placeholder="chapterId filter"
          value={chapterId}
          onChange={(e) => setChapterId(e.target.value)}
        />
        <div className="ml-auto flex items-center gap-3">
          {BANDS.map((b) => (
            <span key={b} className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <span className="w-3 h-3 rounded" style={{ backgroundColor: BAND_COLORS[b] }} /> {b}
            </span>
          ))}
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-x-auto">
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <table className="w-full text-sm border-collapse min-w-[900px]">
            <thead>
              <tr>
                <th className="sticky left-0 bg-white dark:bg-slate-900 px-4 py-3 text-left text-xs uppercase tracking-wider text-slate-500 border-b border-r border-slate-200 dark:border-slate-800 min-w-[120px]">
                  Student
                </th>
                {chapters.map((ch) => (
                  <th key={ch} className="px-1 py-3 text-center border-b border-slate-200 dark:border-slate-800">
                    <div className="text-[10px] font-mono text-slate-400 rotate-0 whitespace-nowrap overflow-hidden text-ellipsis max-w-[70px] mx-auto" title={ch}>
                      {ch}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {students.map((sid) => (
                <tr key={sid} className="border-b border-slate-100 dark:border-slate-800/60">
                  <td className="sticky left-0 bg-white dark:bg-slate-900 px-4 py-1.5 font-mono text-xs text-slate-700 dark:text-slate-200 border-r border-slate-200 dark:border-slate-800">{sid}</td>
                  {chapters.map((ch) => {
                    const cell = cellMap[`${sid}|${ch}`];
                    const color = cell ? BAND_COLORS[cell.masteryBand] || BAND_COLORS['Not assessed'] : '#F1F5F9';
                    return (
                      <td key={ch} className="px-1 py-1.5 text-center" title={cell ? `${cell.masteryBand} · ${cell.attemptCount} attempts · ${cell.accuracyRange}%` : 'Not assessed'}>
                        <span
                          className={cn(
                            'inline-block w-full max-w-[70px] h-6 rounded-md border border-slate-200/70 dark:border-slate-700/50',
                            cell?.inactive && 'bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(100,116,139,0.25)_4px,rgba(100,116,139,0.25)_8px)]'
                          )}
                          style={cell && !cell.inactive ? { backgroundColor: color } : {}}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
              {students.length === 0 && (
                <tr><td colSpan={chapters.length + 1} className="px-4 py-10 text-center text-sm text-slate-500">No consented summaries yet.</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
