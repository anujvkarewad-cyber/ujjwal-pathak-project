import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import '@/App.css';
import DashboardLayout from '@/layouts/DashboardLayout';
import Dashboard from '@/pages/Dashboard';
import Students from '@/pages/Students';
import StudentProfile from '@/pages/StudentProfile';
import DailyTracker from '@/pages/DailyTracker';
import Leaderboard from '@/pages/Leaderboard';
import Announcements from '@/pages/Announcements';
import Notes from '@/pages/Notes';
import Reports from '@/pages/Reports';
import Settings from '@/pages/Settings';
// NEW — AI Content review center
import ReviewQueue from '@/pages/ai-content/ReviewQueue';
import ChapterCoverage from '@/pages/ai-content/ChapterCoverage';
import QuestionReview from '@/pages/ai-content/QuestionReview';
import ScenarioReview from '@/pages/ai-content/ScenarioReview';
import References from '@/pages/ai-content/References';
import Releases from '@/pages/ai-content/Releases';
import AuditHistory from '@/pages/ai-content/AuditHistory';
// NEW — Student analytics
import AnalyticsOverview from '@/pages/analytics/AnalyticsOverview';
import StudentAnalysis from '@/pages/analytics/StudentAnalysis';
import StudentAnalysisDetail from '@/pages/analytics/StudentAnalysisDetail';
import Heatmap from '@/pages/analytics/Heatmap';
import { GroupAnalysis, SubjectAnalysis } from '@/pages/analytics/GroupSubjects';
import WeakAtRisk from '@/pages/analytics/WeakAtRisk';
import ImprovementTracking from '@/pages/analytics/ImprovementTracking';
import FollowUps from '@/pages/analytics/FollowUps';

function App() {
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
          <Route path="/notes" element={<Notes />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
          {/* NEW — AI Content */}
          <Route path="/ai-content/queue" element={<ReviewQueue />} />
          <Route path="/ai-content/coverage" element={<ChapterCoverage />} />
          <Route path="/ai-content/questions" element={<QuestionReview />} />
          <Route path="/ai-content/scenarios" element={<ScenarioReview />} />
          <Route path="/ai-content/references" element={<References />} />
          <Route path="/ai-content/releases" element={<Releases />} />
          <Route path="/ai-content/audit" element={<AuditHistory />} />
          {/* NEW — Analytics */}
          <Route path="/analytics" element={<AnalyticsOverview />} />
          <Route path="/analytics/students" element={<StudentAnalysis />} />
          <Route path="/analytics/students/:id" element={<StudentAnalysisDetail />} />
          <Route path="/analytics/groups" element={<GroupAnalysis />} />
          <Route path="/analytics/subjects" element={<SubjectAnalysis />} />
          <Route path="/analytics/heatmap" element={<Heatmap />} />
          <Route path="/analytics/weak" element={<WeakAtRisk />} />
          <Route path="/analytics/improvement" element={<ImprovementTracking />} />
          <Route path="/analytics/followups" element={<FollowUps />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
