import { Users, UserCheck, ClipboardList, AlertTriangle, Clock, CalendarCheck, Target, LineChart } from 'lucide-react';
import KPICard from '@/components/dashboard/KPICard';
import RecentActivity from '@/components/dashboard/RecentActivity';
import UpcomingTasks from '@/components/dashboard/UpcomingTasks';
import { AttendanceAreaChart, WeeklyStudyBarChart, PerformancePieChart, BatchBarChart } from '@/components/charts/Charts';
import { CardSkeleton, Skeleton } from '@/components/common/Skeleton';
import {
  useDashboardKpis, useRecentActivity, useWeeklyStudy,
  useAttendanceTrend, usePerformanceMix, useBatchOverview, useUpcomingTasks,
} from '@/api/hooks';

const ChartCard = ({ title, subtitle, children, testid, wide }) => (
  <div className={`${wide ? 'lg:col-span-2 ' : ''}bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5`} data-testid={testid}>
    <h3 className="font-heading font-semibold text-slate-900 dark:text-white">{title}</h3>
    {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">{subtitle}</p>}
    {children}
  </div>
);

export default function Dashboard() {
  const { data: k, isLoading: kLoading } = useDashboardKpis();
  const { data: activity } = useRecentActivity();
  const { data: weekly } = useWeeklyStudy();
  const { data: attendance } = useAttendanceTrend();
  const { data: perfMix } = usePerformanceMix();
  const { data: batch } = useBatchOverview();
  const { data: tasks } = useUpcomingTasks();

  const cards = k ? [
    { icon: Users, label: 'Total Students', value: k.total, tone: 'blue', delta: 4, testid: 'kpi-total' },
    { icon: UserCheck, label: "Today's Active", value: k.active, tone: 'emerald', delta: 2, testid: 'kpi-active' },
    { icon: ClipboardList, label: 'Pending Tracker', value: k.pending, tone: 'amber', delta: -3, testid: 'kpi-pending' },
    { icon: AlertTriangle, label: 'At Risk', value: k.atRisk, tone: 'rose', delta: -1, testid: 'kpi-risk' },
    { icon: Clock, label: 'Avg Study Hours', value: k.avgHours, suffix: 'h', tone: 'violet', delta: 6, testid: 'kpi-hours' },
    { icon: CalendarCheck, label: 'Overall Attendance', value: k.avgAttendance, suffix: '%', tone: 'emerald', delta: 3, testid: 'kpi-attendance' },
    { icon: Target, label: 'Overall MCQ Accuracy', value: k.avgMcq, suffix: '%', tone: 'blue', delta: 2, testid: 'kpi-mcq' },
    { icon: LineChart, label: 'Weekly Submission', value: k.weeklySub, suffix: '%', tone: 'slate', delta: 5, testid: 'kpi-submission' },
  ] : [];

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kLoading
          ? Array.from({ length: 8 }).map((_, i) => <CardSkeleton key={i} />)
          : cards.map((c, i) => <KPICard key={i} {...c} />)}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard title="Attendance Trend" subtitle="Weekly attendance across all batches" testid="attendance-chart" wide>
          {attendance ? <AttendanceAreaChart data={attendance} /> : <Skeleton className="h-[260px] w-full" />}
        </ChartCard>
        <ChartCard title="Performance Mix" subtitle="Student distribution by level" testid="performance-chart">
          {perfMix ? <PerformancePieChart data={perfMix} /> : <Skeleton className="h-[260px] w-full" />}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard title="Weekly Study Hours" subtitle="Avg hours vs 7h target" testid="weekly-study">
          {weekly ? <WeeklyStudyBarChart data={weekly} /> : <Skeleton className="h-[260px] w-full" />}
        </ChartCard>
        <ChartCard title="Batch Overview" subtitle="Attendance & MCQ accuracy by batch" testid="batch-overview" wide>
          {batch ? <BatchBarChart data={batch} /> : <Skeleton className="h-[260px] w-full" />}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          {activity ? <RecentActivity items={activity} /> : <Skeleton className="h-96 w-full" />}
        </div>
        {tasks ? <UpcomingTasks tasks={tasks} /> : <Skeleton className="h-96 w-full" />}
      </div>
    </div>
  );
}
