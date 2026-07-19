import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Mail, Phone, MapPin, Calendar, StickyNote } from 'lucide-react';
import { students } from '@/data/students';
import { RiskBadge, StatusBadge } from '@/components/common/RiskBadge';
import { StudentWeeklyLine, StudentMonthlyBar, PerformanceRadar } from '@/components/charts/Charts';
import { cn } from '@/utils/format';

const Stat = ({ label, value, suffix, tone = 'text-slate-900 dark:text-white' }) => (
  <div className="bg-slate-50 dark:bg-slate-800/40 rounded-lg p-4">
    <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{label}</div>
    <div className={cn('mt-1 font-heading text-2xl font-bold', tone)}>{value}{suffix && <span className="text-lg text-slate-400 ml-0.5">{suffix}</span>}</div>
  </div>
);

export default function StudentProfile() {
  const { id } = useParams();
  const s = students.find(x => x.id === id);

  if (!s) {
    return (
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center">
        <p className="text-slate-600 dark:text-slate-300">Student not found.</p>
        <Link to="/students" className="mt-4 inline-flex items-center gap-2 text-[#2563EB] font-medium">
          <ArrowLeft className="w-4 h-4" /> Back to students
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="student-profile">
      <Link to="/students" className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300 hover:text-[#2563EB]" data-testid="back-to-students">
        <ArrowLeft className="w-4 h-4" /> Back to students
      </Link>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
        <div className="flex flex-col sm:flex-row gap-5">
          <img src={s.avatar} alt={s.name} className="w-24 h-24 rounded-2xl object-cover ring-4 ring-slate-100 dark:ring-slate-800" />
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-heading text-2xl font-bold text-slate-900 dark:text-white">{s.name}</h2>
              <StatusBadge status={s.status} />
              <RiskBadge risk={s.risk} />
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{s.id} · {s.level} · {s.batch} · Attempt {s.attempt}</p>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Mail className="w-4 h-4 text-slate-400" />{s.email}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Phone className="w-4 h-4 text-slate-400" />{s.phone}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><MapPin className="w-4 h-4 text-slate-400" />{s.city}</div>
              <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300"><Calendar className="w-4 h-4 text-slate-400" />Joined {s.joinedOn}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Stat label="Attendance" value={s.attendance} suffix="%" tone={s.attendance >= 80 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'} />
        <Stat label="Study Hours / day" value={s.studyHours} suffix="h" />
        <Stat label="MCQ Accuracy" value={s.mcqAccuracy} suffix="%" />
        <Stat label="Weekly Submission" value={s.submissionRate} suffix="%" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Weekly Progress</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Daily study hours & MCQ accuracy</p>
          <StudentWeeklyLine data={s.weekly} />
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Performance Snapshot</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Multi-dimensional view</p>
          <PerformanceRadar student={s} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Monthly Progress</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2 mt-0.5">Attendance, MCQ & hours by week</p>
          <StudentMonthlyBar data={s.monthly} />
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <StickyNote className="w-4 h-4 text-[#2563EB]" />
            <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Mentor Notes</h3>
          </div>
          <ul className="space-y-3">
            {s.mentorNotes.map((n, i) => (
              <li key={i} className="p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40 border border-slate-100 dark:border-slate-800">
                <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">{n.date}</div>
                <p className="text-sm text-slate-700 dark:text-slate-200 mt-1">{n.note}</p>
              </li>
            ))}
          </ul>
          <button className="mt-3 w-full h-10 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold transition-colors" data-testid="add-note-btn">Add Note</button>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Daily Tracker · Last 14 days</h3>
        <div className="mt-4 grid grid-cols-7 sm:grid-cols-14 gap-1.5">
          {s.tracker.map((d, i) => (
            <div key={i} title={`${d.date} · ${d.hours}h · ${d.mcqAccuracy}%`} className={cn('aspect-square rounded-md flex items-center justify-center text-[10px] font-semibold', d.submitted ? 'bg-emerald-500/90 text-white' : 'bg-rose-100 dark:bg-rose-500/20 text-rose-600 dark:text-rose-400')}>
              {d.date.slice(-2)}
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" /> Submitted</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-rose-300 dark:bg-rose-500/40" /> Missed</span>
        </div>
      </div>
    </div>
  );
}
