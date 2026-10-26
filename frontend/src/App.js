import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import '@/App.css';
import DashboardLayout from '@/layouts/DashboardLayout';
import Dashboard from '@/pages/Dashboard';
import Students from '@/pages/Students';
import BatchWorkspace from '@/pages/BatchWorkspace';
import StudentProfile from '@/pages/StudentProfile';
import PasswordReset from '@/pages/PasswordReset';
import DailyTracker from '@/pages/DailyTracker';
import DailyTargets from '@/pages/DailyTargets';
import TargetPlans from '@/pages/TargetPlans';
import Leaderboard from '@/pages/Leaderboard';
import Announcements from '@/pages/Announcements';
import Notes from '@/pages/Notes';
import NotesInbox from '@/pages/NotesInbox';
import Reports from '@/pages/Reports';
import Tests from '@/pages/Tests';
import Workbooks from '@/pages/Workbooks';
import McqScores from '@/pages/McqScores';
import Messages from '@/pages/Messages';
import Login from '@/pages/Login';
import { getToken, setToken, AUTH_EVENT } from '@/api/backendClient';

// Route guard: everything inside the dashboard requires a mentor JWT.
// Any 401 from the API (token expired/invalid) drops back to the login page.
function RequireAuth({ children }) {
  const navigate = useNavigate();
  useEffect(() => {
    const onAuthRequired = () => { setToken(''); navigate('/login', { replace: true }); };
    window.addEventListener(AUTH_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_EVENT, onAuthRequired);
  }, [navigate]);
  if (!getToken()) return <Navigate to="/login" replace />;
  return children;
}
import Settings from '@/pages/Settings';
import SheetSources from '@/pages/SheetSources';
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
      <Toaster position="top-right" richColors />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><DashboardLayout /></RequireAuth>}>
          <Route index element={<Dashboard />} />
          <Route path="/batches" element={<BatchWorkspace />} />
          <Route path="/students" element={<Students />} />
          <Route path="/students/:id" element={<StudentProfile />} />
          <Route path="/password-reset" element={<PasswordReset />} />
          <Route path="/daily-tracker" element={<DailyTracker />} />
          <Route path="/daily-targets" element={<DailyTargets />} />
          <Route path="/target-plans" element={<TargetPlans />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/announcements" element={<Announcements />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/notes-inbox" element={<NotesInbox />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/tests" element={<Tests />} />
          <Route path="/workbooks" element={<Workbooks />} />
          <Route path="/mcq-scores" element={<McqScores />} />
          <Route path="/messages" element={<Messages />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/sheet-sources" element={<SheetSources />} />
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
