import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from '@/components/layout/Sidebar';
import Topbar from '@/components/layout/Topbar';

const TITLES = {
  '/': { title: 'Dashboard', subtitle: 'Overview of your mentorship program' },
  '/students': { title: 'Students', subtitle: 'Manage all enrolled students' },
  '/daily-tracker': { title: 'Daily Tracker', subtitle: 'Track daily submissions across batches' },
  '/leaderboard': { title: 'Leaderboard', subtitle: 'Top performers across time frames' },
  '/announcements': { title: 'Announcements', subtitle: 'Broadcast updates to your students' },
  '/notes': { title: 'Notes', subtitle: 'Mentor notes for students' },
  '/reports': { title: 'Reports', subtitle: 'Detailed batch & student reports' },
  '/settings': { title: 'Settings', subtitle: 'Manage your mentor profile and preferences' },
  '/ai-content': { title: 'MCQ Review', subtitle: 'Approve chapter MCQs before students see them' },
  '/analytics': { title: 'Analytics', subtitle: 'Consented chapter mastery and follow-ups' },
};

export default function DashboardLayout() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const base = '/' + (pathname.split('/')[1] || '');
  const meta = TITLES[base] || TITLES['/students'];

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-950">
      <Sidebar open={open} onClose={() => setOpen(false)} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Topbar onMenu={() => setOpen(true)} title={meta.title} subtitle={meta.subtitle} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="animate-fade-in-up">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
