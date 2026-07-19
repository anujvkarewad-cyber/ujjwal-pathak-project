import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import '@/App.css';
import DashboardLayout from '@/layouts/DashboardLayout';
import Dashboard from '@/pages/Dashboard';
import Students from '@/pages/Students';
import StudentProfile from '@/pages/StudentProfile';
import DailyTracker from '@/pages/DailyTracker';
import Leaderboard from '@/pages/Leaderboard';
import Announcements from '@/pages/Announcements';
import Reports from '@/pages/Reports';
import Settings from '@/pages/Settings';
import { useEffect } from 'react';
import { useTheme } from '@/hooks/useTheme';

function App() {
  // Initialize theme on mount so `.dark` class is applied
  const { theme } = useTheme();
  useEffect(() => { void theme; }, [theme]);

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<DashboardLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="/students" element={<Students />} />
          <Route path="/students/:id" element={<StudentProfile />} />
          <Route path="/daily-tracker" element={<DailyTracker />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/announcements" element={<Announcements />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
