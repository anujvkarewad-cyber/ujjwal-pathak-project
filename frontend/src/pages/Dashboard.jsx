import { Users, UserCheck, ClipboardList, AlertTriangle, Clock, CalendarCheck, Target, LineChart } from 'lucide-react';
import KPICard from '@/components/dashboard/KPICard';
import RecentActivity from '@/components/dashboard/RecentActivity';
import UpcomingTasks from '@/components/dashboard/UpcomingTasks';
import { AttendanceAreaChart, WeeklyStudyBarChart, PerformancePieChart, BatchBarChart } from '@/components/charts/Charts';
import { kpis, recentActivity, weeklyStudy, attendanceTrend, performanceMix, batchOverview, upcomingTasks } from '@/data/dashboard';

export default function Dashboard() {
  const k = kpis();
  const cards = [
    { icon: Users, label: 'Total Students', value: k.total, tone: 'blue', delta: 4, testid: 'kpi-total' },
    { icon: UserCheck, label: "Today's Active", value: k.active, tone: 'emerald', delta: 2, testid: 'kpi-active' },
    { icon: ClipboardList, label: 'Pending Tracker', value: k.pending, tone: 'amber', delta: -3, testid: 'kpi-pending' },
    { icon: AlertTriangle, label: 'At Risk', value: k.atRisk, tone: 'rose', delta: -1, testid: 'kpi-risk' },
    { icon: Clock, label: 'Avg Study Hours', value: k.avgHours, suffix: 'h', tone: 'violet', delta: 6, testid: 'kpi-hours' },
    { icon: CalendarCheck, label: 'Overall Attendance', value: k.avgAttendance, suffix: '%', tone: 'emerald', delta: 3, testid: 'kpi-attendance' },
    { icon: Target, label: 'Overall MCQ Accuracy', value: k.avgMcq, suffix: '%', tone: 'blue', delta: 2, testid: 'kpi-mcq' },
    { icon: LineChart, label: 'Weekly Submission', value: k.weeklySub, suffix: '%', tone: 'slate', delta: 5, testid: 'kpi-submission' },
  ];

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((c, i) => <KPICard key={i} {...c} />)}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="attendance-chart">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Attendance Trend</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Weekly attendance across all batches</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-[#2563EB]" />
              <span className="text-xs text-slate-500 dark:text-slate-400">Attendance %</span>
            </div>
          </div>
          <AttendanceAreaChart data={attendanceTrend} />
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="performance-chart">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Performance Mix</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Student distribution by level</p>
          <PerformancePieChart data={performanceMix} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="weekly-study">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Weekly Study Hours</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Avg hours vs 7h target</p>
          <WeeklyStudyBarChart data={weeklyStudy} />
        </div>
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5" data-testid="batch-overview">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Batch Overview</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Attendance & MCQ accuracy by batch</p>
          <BatchBarChart data={batchOverview} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2"><RecentActivity items={recentActivity} /></div>
        <UpcomingTasks tasks={upcomingTasks} />
      </div>
    </div>
  );
}
