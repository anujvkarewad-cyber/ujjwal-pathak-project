import { Search, Bell, Sun, Moon, Menu, ShieldCheck } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { useState, useEffect } from 'react';
import { getMentorNotifications } from '@/api/dashboard';
import LoginDialog from '@/components/content/LoginDialog';

export default function Topbar({ onMenu, title, subtitle }) {
  const { theme, toggle } = useTheme();
  const [notifications, setNotifications] = useState([]);
  const [open, setOpen] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
 
useEffect(() => {
  loadNotifications();
}, []);

async function loadNotifications() {
  try {
    const data = await getMentorNotifications();
    setNotifications(data || []);
  } catch (e) {
    console.error(e);
  }
}
  return (
    <header className="h-16 flex items-center gap-4 px-4 sm:px-6 lg:px-8 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur sticky top-0 z-20">
      <button
        onClick={onMenu}
        className="lg:hidden p-2 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
        aria-label="Open menu"
        data-testid="topbar-menu-btn"
      >
        <Menu className="w-5 h-5" />
      </button>

      <div className="hidden sm:block min-w-0">
        <h1 className="font-heading text-lg sm:text-xl font-semibold text-slate-900 dark:text-white truncate" data-testid="topbar-title">{title}</h1>
        {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{subtitle}</p>}
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <button
          onClick={() => setLoginOpen(true)}
          className="p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-[#2563EB] transition-colors"
          aria-label="Mentor sign-in for AI Content and Analytics"
          data-testid="mentor-login-btn"
          title="Mentor sign-in (AI Content + Analytics)"
        >
          <ShieldCheck className="w-[18px] h-[18px]" />
        </button>
        <div className="hidden md:flex items-center gap-2 h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 w-72">
          <Search className="w-4 h-4 text-slate-400" />
          <input
            data-testid="topbar-search"
            className="bg-transparent outline-none text-sm w-full text-slate-700 dark:text-slate-200 placeholder:text-slate-400"
            placeholder="Search students, batches..."
          />
          <kbd className="hidden lg:inline text-[10px] font-mono px-1.5 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-slate-500">⌘K</kbd>
        </div>

        <button
          onClick={toggle}
          className="p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors"
          aria-label="Toggle theme"
          data-testid="theme-toggle"
        >
          {theme === 'dark' ? <Sun className="w-[18px] h-[18px]" /> : <Moon className="w-[18px] h-[18px]" />}
        </button>

        <div className="relative">

  <button
    onClick={() => setOpen(!open)}
    className="relative p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors"
    aria-label="Notifications"
  >
    <Bell className="w-[18px] h-[18px]" />

    {notifications.length > 0 && (
      <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] rounded-full w-5 h-5 flex items-center justify-center">
        {notifications.length}
      </span>
    )}
  </button>

          {open && (
    <div className="absolute right-0 mt-2 w-96 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-slate-200 dark:border-slate-700 z-50">

      {notifications.length === 0 ? (
        <div className="p-4 text-sm text-slate-500">
          No notifications
        </div>
      ) : (
        notifications.map((n, i) => (
          <div key={i} className="p-4 border-b border-slate-200 dark:border-slate-700">
            <div className="font-semibold">{n.title}</div>
            <div className="text-sm text-slate-500">{n.message}</div>
          </div>
        ))
      )}

    </div>
  )}

</div>
      </div>

      <LoginDialog open={loginOpen} onOpenChange={setLoginOpen} />
    </header>
  );
}
