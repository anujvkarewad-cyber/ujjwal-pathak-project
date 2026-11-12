import {
  Users,
  UserCheck,
  ClipboardList,
  AlertTriangle,
  Clock,
  CalendarCheck,
  LineChart,
  BookOpenCheck,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import KPICard from "@/components/dashboard/KPICard";
import RecentActivity from "@/components/dashboard/RecentActivity";
import TrackerFollowUps from "@/components/dashboard/TrackerFollowUps";
import {
  AttendanceAreaChart,
  WeeklyStudyBarChart,
  PerformancePieChart,
  BatchBarChart,
} from "@/components/charts/Charts";
import { CardSkeleton, Skeleton } from "@/components/common/Skeleton";
import { useDashboardKpis } from "@/api/hooks";
import { useContentStats } from "@/api/hooks-content";

const ChartCard = ({ title, subtitle, children, testid, wide }) => (
  <div
    className={`${wide ? "lg:col-span-2 " : ""}bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5`}
    data-testid={testid}
  >
    <h3 className="font-heading font-semibold text-slate-900 dark:text-white">
      {title}
    </h3>
    {subtitle && (
      <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">
        {subtitle}
      </p>
    )}
    {children}
  </div>
);

function UnavailablePanel({ onRetry, message = "Live tracker data is unavailable." }) {
  return (
    <div className="h-[260px] w-full flex flex-col items-center justify-center text-center p-6">
      <div className="w-8 h-8 rounded-full bg-amber-50 text-amber-600 flex items-center justify-center mb-2">
        <AlertTriangle className="w-5 h-5" />
      </div>
      <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="h-9 px-4 rounded-lg border border-slate-200 dark:border-slate-800 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const {
    data: k,
    isLoading: kLoading,
    isError: kError,
    refetch: refetchKpis,
  } = useDashboardKpis();
  const { data: mcqStats } = useContentStats();

  // Cards and charts share one backend snapshot. Never substitute mock/legacy
  // values or silently turn a failed Sheet read into 0% attendance.
  const trackerAvailable = k?.trackerDataAvailable === true;
  const metric = (field) => trackerAvailable && k?.[field] != null ? k[field] : "—";
  const cards = [
    {
      icon: Users,
      label: "Total Students",
      value: k?.total ?? "—",
      tone: "blue",
      testid: "kpi-total",
    },
    {
      icon: UserCheck,
      label: "Today's Active",
      value: metric("active"),
      tone: "emerald",
      testid: "kpi-active",
    },
    {
      icon: ClipboardList,
      label: "Pending Tracker",
      value: metric("pending"),
      tone: "amber",
      testid: "kpi-pending",
    },
    {
      icon: AlertTriangle,
      label: "At Risk",
      value: metric("atRisk"),
      tone: "rose",
      testid: "kpi-risk",
    },
    {
      icon: Clock,
      label: "Avg Weekly Study",
      value: metric("avgHours"),
      suffix: "h",
      tone: "violet",
      testid: "kpi-hours",
    },
    {
      icon: CalendarCheck,
      label: "30-Day Attendance",
      value: metric("avgAttendance"),
      suffix: "%",
      tone: "emerald",
      testid: "kpi-attendance",
    },
    {
      icon: LineChart,
      label: "7-Day Submission",
      value: metric("weeklySub"),
      suffix: "%",
      tone: "slate",
      testid: "kpi-submission",
    },
  ];

  const unavailable = kError || (k && !trackerAvailable);
  const panelMessage = kError
    ? "Dashboard data could not be loaded."
    : "Tracker source unavailable; metrics are hidden rather than shown as zero.";
  const renderChart = (data, Chart) => {
    if (kLoading) return <Skeleton className="h-[260px] w-full" />;
    if (unavailable) return <UnavailablePanel onRetry={refetchKpis} message={panelMessage} />;
    if (!Array.isArray(data) || data.length === 0) {
      return <UnavailablePanel message="No live records are available for this period." />;
    }
    return <Chart data={data} />;
  };

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div>
          <h2 className="font-semibold">Batch & group workspaces</h2>
          <p className="text-xs text-slate-500">
            Current roster, day-wise tracker and existing student records.
          </p>
        </div>
        <button
          onClick={() => navigate("/batches")}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white"
        >
          Open batches
        </button>
      </div>

      {(unavailable || k?.trackerDataAvailable) && (
        <div
          role="status"
          className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${
            unavailable
              ? "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
              : "border-slate-200 bg-white text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
          }`}
        >
          <span>
            {unavailable
              ? `${panelMessage} ${k?.trackerSource || ""}`
              : `Live data: ${k.trackerSource}. Active today includes tracker, MCQ/test activity and successful app sign-ins.`}
          </span>
          {unavailable && (
            <button onClick={() => refetchKpis()} className="font-semibold underline">
              Retry
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <button
          type="button"
          onClick={() => navigate("/ai-content/queue")}
          className="text-left"
        >
          <KPICard
            icon={BookOpenCheck}
            label="MCQs awaiting approval"
            value={mcqStats?.needsReview ?? "—"}
            tone="amber"
            testid="kpi-mcq-pending"
          />
        </button>
        {kLoading
          ? Array.from({ length: 7 }).map((_, i) => <CardSkeleton key={i} />)
          : cards.map((card) => <KPICard key={card.testid} {...card} />)}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          title="Attendance Trend"
          subtitle="Weekly tracker attendance across all batches"
          testid="attendance-chart"
          wide
        >
          {renderChart(k?.attendanceTrend, AttendanceAreaChart)}
        </ChartCard>
        <ChartCard
          title="Performance Mix"
          subtitle="30-day attendance and 7-day tracker submission"
          testid="performance-chart"
        >
          {renderChart(k?.performanceMix, PerformancePieChart)}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ChartCard
          title="Weekly Study Hours"
          subtitle="Average hours per student per day · 7h target"
          testid="weekly-study"
        >
          {renderChart(k?.weeklyStudy, WeeklyStudyBarChart)}
        </ChartCard>
        <ChartCard
          title="Batch Overview"
          subtitle="30-day tracker attendance by batch"
          testid="batch-overview"
          wide
        >
          {renderChart(k?.batchOverview, BatchBarChart)}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          {kLoading ? (
            <Skeleton className="h-96 w-full" />
          ) : unavailable ? (
            <div className="h-96 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <UnavailablePanel onRetry={refetchKpis} message={panelMessage} />
            </div>
          ) : (
            <RecentActivity items={k?.recentActivity || []} />
          )}
        </div>
        <TrackerFollowUps
          items={k?.followUps || []}
          loading={kLoading}
          available={trackerAvailable && !kError}
        />
      </div>
    </div>
  );
}
