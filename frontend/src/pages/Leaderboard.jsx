import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Trophy, Medal, Award, Crown } from 'lucide-react';
import { useLeaderboard } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const TABS = [
  { key: 'overall', label: 'Overall' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
];

export default function Leaderboard() {
  const [tab, setTab] = useState('overall');
  const { data: ranked = [], isLoading } = useLeaderboard(tab);

  const top3 = ranked.slice(0, 3);
  const rest = ranked.slice(3, 20);
  const podium = [
    { s: top3[1], icon: Medal, tone: 'from-slate-200 to-slate-100 dark:from-slate-700 dark:to-slate-800', rank: 2, height: 'h-32' },
    { s: top3[0], icon: Crown, tone: 'from-amber-100 to-amber-50 dark:from-amber-500/20 dark:to-amber-500/5', rank: 1, height: 'h-40' },
    { s: top3[2], icon: Award, tone: 'from-orange-100 to-orange-50 dark:from-orange-500/20 dark:to-orange-500/5', rank: 3, height: 'h-24' },
  ];

  return (
    <div className="space-y-6" data-testid="leaderboard-page">
      <div className="inline-flex p-1 bg-slate-100 dark:bg-slate-800/60 rounded-lg">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            data-testid={`tab-${t.key}`}
            className={cn(
              'h-9 px-5 text-sm font-semibold rounded-md transition-colors',
              tab === t.key ? 'bg-white dark:bg-slate-900 text-[#2563EB] shadow-sm' : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-3 gap-4 items-end">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-32 w-full" />)}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4 items-end">
          {podium.map(({ s, icon: Icon, tone, rank, height }) => s && (
            <div key={rank} className={cn('rounded-xl p-5 border border-slate-200 dark:border-slate-800 bg-gradient-to-b', tone, height, 'flex flex-col items-center justify-end text-center')}>
              <Icon className={cn('w-6 h-6 mb-2', rank === 1 ? 'text-amber-500' : rank === 2 ? 'text-slate-500' : 'text-orange-500')} />
              <img src={s.avatar} alt={s.name} className="w-14 h-14 rounded-full object-cover ring-4 ring-white dark:ring-slate-900 mb-2" />
              <div className="font-heading font-bold text-slate-900 dark:text-white text-sm">{s.name}</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{s.batch}</div>
              <div className="mt-1 font-heading text-xl font-bold text-[#2563EB]">{s.score}</div>
            </div>
          ))}
        </div>
      )}

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2">
          <Trophy className="w-4 h-4 text-[#2563EB]" />
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Top Performers</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
              <th className="px-5 py-3 w-16">Rank</th>
              <th className="px-5 py-3">Student</th>
              <th className="px-5 py-3">Batch</th>
              <th className="px-5 py-3">Attendance</th>
              <th className="px-5 py-3">MCQ</th>
              <th className="px-5 py-3 text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {rest.map((s, i) => (
              <tr key={s.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
                <td className="px-5 py-3 font-heading font-bold text-slate-500 dark:text-slate-400">#{i + 4}</td>
                <td className="px-5 py-3">
                  <Link to={`/students/${s.id}`} className="flex items-center gap-3 hover:text-[#2563EB]">
                    <img src={s.avatar} alt="" className="w-8 h-8 rounded-full object-cover" />
                    <span className="font-semibold text-slate-900 dark:text-white">{s.name}</span>
                  </Link>
                </td>
                <td className="px-5 py-3 text-slate-600 dark:text-slate-300">{s.batch}</td>
                <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.attendance}%</td>
                <td className="px-5 py-3 text-slate-700 dark:text-slate-200">{s.mcqAccuracy}%</td>
                <td className="px-5 py-3 text-right font-heading font-bold text-[#2563EB]">{s.score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
