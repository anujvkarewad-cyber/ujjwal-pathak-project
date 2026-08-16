import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Users, ClipboardList, Trophy, Megaphone, FileText, FileBarChart2, Settings, GraduationCap,
  Sparkles, ListChecks, Grid3X3, BookOpenCheck, Layers, FlaskConical, PackageCheck, History,
  BarChart3, UserSearch, GitCompareArrows, School, Table2, UserX, TrendingUp, CheckSquare,
} from 'lucide-react';
import { cn } from '@/utils/format';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, testid: 'nav-dashboard' },
  { to: '/ai-content/queue', label: 'MCQ Review', icon: BookOpenCheck, testid: 'nav-mcq-review' },
  { to: '/students', label: 'Students', icon: Users, testid: 'nav-students' },
  { to: '/daily-tracker', label: 'Daily Tracker', icon: ClipboardList, testid: 'nav-daily-tracker' },
  { to: '/leaderboard', label: 'Leaderboard', icon: Trophy, testid: 'nav-leaderboard' },
  { to: '/announcements', label: 'Announcements', icon: Megaphone, testid: 'nav-announcements' },
  { to: '/notes', label: 'Notes', icon: FileText, testid: 'nav-notes' },
  { to: '/reports', label: 'Reports', icon: FileBarChart2, testid: 'nav-reports' },
  { to: '/settings', label: 'Settings', icon: Settings, testid: 'nav-settings' },
];

// NEW — AI Content review & publishing center (additive; existing nav untouched)
const AI_CONTENT_NAV = [
  { to: '/ai-content/queue', label: 'Review Queue', icon: ListChecks, testid: 'nav-ai-queue' },
  { to: '/ai-content/coverage', label: 'Chapter Coverage', icon: Grid3X3, testid: 'nav-ai-coverage' },
  { to: '/ai-content/questions', label: 'Question Review', icon: BookOpenCheck, testid: 'nav-ai-questions' },
  { to: '/ai-content/scenarios', label: 'Scenario Review', icon: Layers, testid: 'nav-ai-scenarios' },
  { to: '/ai-content/references', label: 'Calibration References', icon: FlaskConical, testid: 'nav-ai-references' },
  { to: '/ai-content/releases', label: 'Approved Releases', icon: PackageCheck, testid: 'nav-ai-releases' },
  { to: '/ai-content/audit', label: 'Audit History', icon: History, testid: 'nav-ai-audit' },
];

// NEW — student analytics (additive)
const ANALYTICS_NAV = [
  { to: '/analytics', label: 'All Students Overview', icon: BarChart3, testid: 'nav-an-overview' },
  { to: '/analytics/students', label: 'Student Profile Analysis', icon: UserSearch, testid: 'nav-an-students' },
  { to: '/analytics/groups', label: 'Group I / Group II', icon: GitCompareArrows, testid: 'nav-an-groups' },
  { to: '/analytics/subjects', label: 'Subject Analysis', icon: School, testid: 'nav-an-subjects' },
  { to: '/analytics/heatmap', label: 'Chapter Heatmap', icon: Table2, testid: 'nav-an-heatmap' },
  { to: '/analytics/weak', label: 'Weak & At-Risk', icon: UserX, testid: 'nav-an-weak' },
  { to: '/analytics/improvement', label: 'Improvement Tracking', icon: TrendingUp, testid: 'nav-an-improvement' },
  { to: '/analytics/followups', label: 'Follow-up Actions', icon: CheckSquare, testid: 'nav-an-followups' },
];

export default function Sidebar({ open, onClose }) {
  return (
    <>
      {open && (
        <div
          onClick={onClose}
          className="lg:hidden fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-30"
          data-testid="sidebar-backdrop"
        />
      )}
      <aside
        data-testid="sidebar"
        className={cn(
          'fixed lg:static inset-y-0 left-0 z-40 w-72 flex-shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col transform transition-transform duration-200',
          open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        )}
      >
        <div className="h-16 flex items-center gap-3 px-6 border-b border-slate-200 dark:border-slate-800">
          <div className="w-9 h-9 rounded-xl bg-[#2563EB] flex items-center justify-center shadow-sm shadow-blue-500/20">
            <GraduationCap className="w-5 h-5 text-white" strokeWidth={2.2} />
          </div>
          <div className="leading-tight">
            <div className="font-heading font-bold text-[15px] text-slate-900 dark:text-white">Ujjwal Pathak</div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Mentorship</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5 space-y-1">
          {[
            { title: 'Main', items: NAV },
            { title: 'AI Content', items: AI_CONTENT_NAV, icon: Sparkles },
            { title: 'Analytics', items: ANALYTICS_NAV },
          ].map(({ title, items, icon: GroupIcon }) => (
            <div key={title}>
              <div className="px-3 pt-3 pb-2 text-[10px] uppercase tracking-[0.22em] font-semibold text-slate-400 dark:text-slate-500 flex items-center gap-1.5">
                {GroupIcon && <GroupIcon className="w-3 h-3" />}
                {title}
              </div>
              {items.map(({ to, label, icon: Icon, testid }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  onClick={onClose}
                  data-testid={testid}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium',
                      'transition-colors duration-150',
                      isActive
                        ? 'bg-[#2563EB] text-white shadow-sm shadow-blue-500/25'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-white'
                    )
                  }
                >
                  <Icon className="w-[18px] h-[18px]" strokeWidth={2} />
                  <span>{label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="border-t border-slate-200 dark:border-slate-800 p-4">
          <div className="flex items-center gap-3 px-2">
            <img
              src="https://images.unsplash.com/photo-1589386417686-0d34b5903d23?crop=entropy&cs=srgb&fm=jpg&q=85&w=200"
              alt="Ujjwal Pathak"
              className="w-10 h-10 rounded-full object-cover ring-2 ring-slate-100 dark:ring-slate-800"
            />
            <div className="min-w-0">
              <div className="font-semibold text-sm text-slate-900 dark:text-white truncate">Ujjwal Pathak</div>
              <div className="text-xs text-slate-500 dark:text-slate-400 truncate">Mentor · CA</div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
