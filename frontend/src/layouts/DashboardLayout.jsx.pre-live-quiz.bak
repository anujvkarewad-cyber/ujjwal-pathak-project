import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import ErrorBoundary from '@/components/common/ErrorBoundary';
import Sidebar from '@/components/layout/Sidebar';
import Topbar from '@/components/layout/Topbar';

const TITLES = {
  '/batches': { title: 'Batches & groups', subtitle: 'Current enrollment · exclusive group workspaces' },
  '/': { title: 'Dashboard', subtitle: 'Overview of your mentorship program' },
  '/students': { title: 'Students', subtitle: 'Manage all enrolled students' },
  '/daily-tracker': { title: 'Daily Tracker', subtitle: 'Track daily submissions across batches' },
  '/daily-targets': { title: 'Daily Targets', subtitle: 'Upload a target by subject, group, batch, and attempt' },
  '/target-plans': { title: 'Target Plans', subtitle: 'Create and manage multi-day study plans' },
  '/leaderboard': { title: 'Leaderboard', subtitle: 'Top performers across time frames' },
  '/announcements': { title: 'Announcements', subtitle: 'Broadcast updates to your students' },
  '/notes': { title: 'Notes', subtitle: 'Mentor notes for students' },
  '/notes-inbox': { title: 'Notes Inbox', subtitle: 'Publish waiting Drive PDFs to batches & groups' },
  '/reports': { title: 'Reports', subtitle: 'Detailed batch & student reports' },
  '/tests': { title: 'Tests', subtitle: 'Student test submissions and self-evaluation marks' },
  '/workbooks': { title: 'Audit & SM workbooks', subtitle: 'Mentor-reviewed source mapping and practice answer keys' },
  '/messages': { title: 'Messages', subtitle: 'Student messages from the app — read and reply' },
  '/sheet-sources': { title: 'Sheet Sources', subtitle: 'Private workbook directory and source-health guidance' },
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
            {/* One broken screen must not white out the whole dashboard (17-Oct-2026). */}
            <ErrorBoundary key={location.pathname} label="This screen">
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}
