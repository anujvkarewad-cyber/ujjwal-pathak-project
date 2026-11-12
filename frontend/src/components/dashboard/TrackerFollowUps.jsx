import { AlertTriangle, ArrowUpRight, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/utils/format";
import { Skeleton } from "@/components/common/Skeleton";

const priorityTone = {
  high: "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400",
  medium: "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400",
};

export default function TrackerFollowUps({ items = [], loading = false, available = true }) {
  return (
    <section
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 h-full"
      data-testid="tracker-follow-ups"
    >
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">
            Tracker Follow-up
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Students expected to submit today
          </p>
        </div>
        <Link
          to="/daily-tracker"
          className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400"
        >
          Open tracker <ArrowUpRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      ) : !available ? (
        <div className="min-h-48 flex items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
          Tracker data unavailable. No follow-up list is shown.
        </div>
      ) : items.length === 0 ? (
        <div className="min-h-48 flex items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
          No expected tracker submissions are pending today.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.studentId}
              className="flex items-start gap-3 p-3 rounded-lg border border-slate-100 dark:border-slate-800"
            >
              <div
                className={cn(
                  "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
                  item.priority === "high"
                    ? "bg-rose-50 text-rose-600 dark:bg-rose-500/10 dark:text-rose-400"
                    : "bg-amber-50 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400",
                )}
              >
                <AlertTriangle className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <Link
                  to={`/students/${encodeURIComponent(item.studentId)}`}
                  className="text-sm font-semibold text-slate-800 hover:text-blue-600 dark:text-slate-200 dark:hover:text-blue-400"
                >
                  {item.student}
                </Link>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  {item.reason}{item.batch ? ` · ${item.batch}` : ""}
                </p>
                <div className="mt-1 flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
                  <Clock className="w-3 h-3" />
                  {item.attendance == null
                    ? "Today"
                    : `30-day attendance ${item.attendance}%`}
                </div>
              </div>
              <span
                className={cn(
                  "inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide",
                  priorityTone[item.priority] || priorityTone.medium,
                )}
              >
                {item.priority || "medium"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
