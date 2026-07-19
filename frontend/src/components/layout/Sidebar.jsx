import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, ClipboardList, Trophy, Megaphone, FileBarChart2, Settings, GraduationCap } from 'lucide-react';
import { cn } from '@/utils/format';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, testid: 'nav-dashboard' },
  { to: '/students', label: 'Students', icon: Users, testid: 'nav-students' },
  { to: '/daily-tracker', label: 'Daily Tracker', icon: ClipboardList, testid: 'nav-daily-tracker' },
  { to: '/leaderboard', label: 'Leaderboard', icon: Trophy, testid: 'nav-leaderboard' },
  { to: '/announcements', label: 'Announcements', icon: Megaphone, testid: 'nav-announcements' },
  { to: '/reports', label: 'Reports', icon: FileBarChart2, testid: 'nav-reports' },
  { to: '/settings', label: 'Settings', icon: Settings, testid: 'nav-settings' },
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
          <div className="px-3 pb-2 text-[10px] uppercase tracking-[0.22em] font-semibold text-slate-400 dark:text-slate-500">
            Main
          </div>
          {NAV.map(({ to, label, icon: Icon, testid }) => (
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
