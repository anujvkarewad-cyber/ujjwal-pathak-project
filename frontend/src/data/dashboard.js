import { students } from './students';

export const kpis = () => {
  const total = students.length;
  const active = students.filter(s => s.status === 'Active').length;
  const atRisk = students.filter(s => s.risk === 'At Risk').length;
  const pending = students.filter(s => !s.tracker[s.tracker.length - 1].submitted).length;
  const avgHours = +(students.reduce((a, s) => a + s.studyHours, 0) / total).toFixed(1);
  const avgAttendance = Math.round(students.reduce((a, s) => a + s.attendance, 0) / total);
  const avgMcq = Math.round(students.reduce((a, s) => a + s.mcqAccuracy, 0) / total);
  const weeklySub = Math.round(students.reduce((a, s) => a + s.submissionRate, 0) / total);
  return { total, active, atRisk, pending, avgHours, avgAttendance, avgMcq, weeklySub };
};

export const recentActivity = [
  { id: 1, type: 'submission', student: 'Aarav Sharma', action: 'submitted daily tracker', time: '2 min ago', avatar: 0 },
  { id: 2, type: 'mcq', student: 'Diya Patel', action: 'completed 50 MCQs — 92% accuracy', time: '18 min ago', avatar: 1 },
  { id: 3, type: 'risk', student: 'Rohan Verma', action: 'flagged At Risk (attendance dropped)', time: '1 hr ago', avatar: 2 },
  { id: 4, type: 'attendance', student: 'Kavya Iyer', action: 'marked present for morning session', time: '2 hr ago', avatar: 3 },
  { id: 5, type: 'note', student: 'Ishaan Nair', action: 'received a mentor note', time: '3 hr ago', avatar: 4 },
  { id: 6, type: 'submission', student: 'Priya Gupta', action: 'submitted weekly review', time: '5 hr ago', avatar: 5 },
];

export const weeklyStudy = [
  { day: 'Mon', hours: 6.2, target: 7 },
  { day: 'Tue', hours: 7.1, target: 7 },
  { day: 'Wed', hours: 5.8, target: 7 },
  { day: 'Thu', hours: 7.9, target: 7 },
  { day: 'Fri', hours: 6.5, target: 7 },
  { day: 'Sat', hours: 8.4, target: 7 },
  { day: 'Sun', hours: 4.2, target: 7 },
];

export const attendanceTrend = [
  { week: 'W1', attendance: 82 },
  { week: 'W2', attendance: 85 },
  { week: 'W3', attendance: 79 },
  { week: 'W4', attendance: 88 },
  { week: 'W5', attendance: 91 },
  { week: 'W6', attendance: 87 },
  { week: 'W7', attendance: 90 },
  { week: 'W8', attendance: 93 },
];

export const performanceMix = [
  { name: 'Excellent', value: 12, color: '#10B981' },
  { name: 'Good', value: 18, color: '#2563EB' },
  { name: 'Average', value: 14, color: '#F59E0B' },
  { name: 'At Risk', value: 6, color: '#EF4444' },
];

export const batchOverview = [
  { name: 'Super 30', students: 30, attendance: 92, mcq: 84 },
  { name: 'Super 11', students: 11, attendance: 88, mcq: 79 },
  { name: 'Last 15 Days', students: 4, attendance: 76, mcq: 71 },
  { name: 'Last 40 Days', students: 5, attendance: 81, mcq: 74 },
];

export const upcomingTasks = [
  { id: 1, title: 'Weekly review call — Super 30', due: 'Today, 6:00 PM', priority: 'high' },
  { id: 2, title: 'Publish mock test results', due: 'Tomorrow', priority: 'medium' },
  { id: 3, title: 'Send progress reports to parents', due: 'Feb 24', priority: 'medium' },
  { id: 4, title: 'Schedule 1:1 with At Risk students', due: 'Feb 25', priority: 'high' },
  { id: 5, title: 'Update MCQ question bank', due: 'Feb 27', priority: 'low' },
];
