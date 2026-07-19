import { Search, Bell, Sun, Moon, Menu } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';

export default function Topbar({ onMenu, title, subtitle }) {
  const { theme, toggle } = useTheme();
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

        <button
          className="relative p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors"
          aria-label="Notifications"
          data-testid="topbar-notifications"
        >
          <Bell className="w-[18px] h-[18px]" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#2563EB] ring-2 ring-white dark:ring-slate-900" />
        </button>
      </div>
    </header>
  );
}
