import { useState } from 'react';
import { Download, FileBarChart2, UserSquare2 } from 'lucide-react';
import { BatchBarChart } from '@/components/charts/Charts';
import { useBatchReport, useStudentReport } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const TABS = [
  { key: 'batch', label: 'Batch Report', icon: FileBarChart2 },
  { key: 'student', label: 'Student Report', icon: UserSquare2 },
];

export default function Reports() {
  const [tab, setTab] = useState('batch');
  const { data: batch, isLoading: batchLoading } = useBatchReport();
  const { data: studentReport, isLoading: srLoading } = useStudentReport();

  return (
    <div className="space-y-6" data-testid="reports-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex p-1 bg-slate-100 dark:bg-slate-800/60 rounded-lg">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              data-testid={`report-tab-${t.key}`}
              className={cn(
                'h-9 px-4 text-sm font-semibold rounded-md inline-flex items-center gap-2 transition-colors',
                tab === t.key ? 'bg-white dark:bg-slate-900 text-[#2563EB] shadow-sm' : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
              )}
            >
              <t.icon className="w-4 h-4" /> {t.label}
            </button>
          ))}
        </div>
        <button data-testid="export-btn" className="h-10 px-4 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center gap-2 transition-colors">
          <Download className="w-4 h-4" /> Export Report
        </button>
      </div>

      {tab === 'batch' ? (
        <>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
            <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Batch Performance</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Comparative view — attendance & MCQ accuracy</p>
            {batchLoading || !batch ? <Skeleton className="h-[260px] w-full" /> : <BatchBarChart data={batch} />}
          </div>
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                  <th className="px-5 py-3">Batch</th>
                  <th className="px-5 py-3">Students</th>
                  <th className="px-5 py-3">Avg Attendance</th>
                  <th className="px-5 py-3">Avg MCQ</th>
                  <th className="px-5 py-3">Health</th>
                </tr>
              </thead>
              <tbody>
                {(batch || []).map(b => (
                  <tr key={b.name} className="border-b border-slate-100 dark:border-slate-800">
                    <td className="px-5 py-3 font-semibold text-slate-900 dark:text-white">{b.name}</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">{b.students}</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">{b.attendance}%</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">{b.mcq}%</td>
                    <td className="px-5 py-3">
                      <span className={cn(
                        'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium border',
                        b.attendance >= 85 ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20' : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20'
                      )}>
                        {b.attendance >= 85 ? 'Healthy' : 'Needs Focus'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                  <th className="px-5 py-3">Student</th>
                  <th className="px-5 py-3">Batch</th>
                  <th className="px-5 py-3">Attendance</th>
                  <th className="px-5 py-3">Study Hours</th>
                  <th className="px-5 py-3">MCQ %</th>
                  <th className="px-5 py-3">Submission %</th>
                </tr>
              </thead>
              <tbody>
                {srLoading && Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-slate-100 dark:border-slate-800"><td className="px-5 py-3" colSpan={6}><Skeleton className="h-8 w-full" /></td></tr>
                ))}
                {(studentReport || []).slice(0, 20).map(s => (
                  <tr key={s.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <img src={s.avatar} alt="" className="w-8 h-8 rounded-full object-cover" />
                        <div>
                          <div className="font-semibold text-slate-900 dark:text-white">{s.name}</div>
                          <div className="text-xs text-slate-500">{s.id}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-slate-600 dark:text-slate-300">{s.batch}</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.attendance}%</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.studyHours}h</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.mcqAccuracy}%</td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.submissionRate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
