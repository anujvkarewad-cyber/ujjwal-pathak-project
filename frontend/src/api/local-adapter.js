// Local mock adapter. Reads from src/data/*.js and serves the same shapes
// that the future Google Apps Script backend must return.
//
// CONTRACT: Each `case` returns the exact JSON payload the real Apps Script
// `doPost({ action, payload })` should return in `result`.
//
// To swap this out: build a Google Apps Script that switches on `action` and
// returns `{ result: <shape below> }`. No frontend changes needed.

import { students as SEED_STUDENTS, batchOptions, attemptOptions, groupOptions, statusOptions } from '@/data/students';
import {
  kpis as computeKpis,
  recentActivity,
  weeklyStudy,
  attendanceTrend,
  performanceMix,
  batchOverview,
  upcomingTasks,
} from '@/data/dashboard';
import { announcements as SEED_ANNOUNCEMENTS } from '@/data/announcements';

// In-memory mutable state so create/update/toggle calls behave like a real backend
const state = {
  students: SEED_STUDENTS.map(s => ({ ...s, mentorNotes: [...s.mentorNotes] })),
  announcements: [...SEED_ANNOUNCEMENTS],
  mentor: {
    name: 'Ujjwal Pathak',
    email: 'mentor@upmentorship.in',
    avatar: 'https://images.unsplash.com/photo-1589386417686-0d34b5903d23?crop=entropy&cs=srgb&fm=jpg&q=85&w=200',
  },
  notifications: { emailNotif: true, smsNotif: false, dailyDigest: true },
};

function scoreForMode(s, mode) {
  if (mode === 'weekly') {
    const avgH = s.weekly.reduce((a, w) => a + w.hours, 0) / s.weekly.length;
    return Math.round(avgH * 10);
  }
  if (mode === 'monthly') {
    const avgA = s.monthly.reduce((a, m) => a + m.attendance, 0) / s.monthly.length;
    return Math.round(avgA);
  }
  return Math.round((s.attendance + s.submissionRate) / 2);
}

export function handle(action, payload = {}) {
  switch (action) {
    // ── Students ──────────────────────────────────────────────────────────
    case 'students.list':
      return {
        students: state.students,
        options: { batchOptions, attemptOptions, groupOptions, statusOptions },
      };
    case 'students.get':
      return state.students.find(s => s.id === payload.id) || null;
    case 'students.addNote': {
      const s = state.students.find(x => x.id === payload.id);
      if (!s) throw new Error('Student not found');
      s.mentorNotes.unshift({ date: new Date().toISOString().slice(0, 10), note: payload.note });
      return { ok: true, notes: s.mentorNotes };
    }

    // ── Dashboard ─────────────────────────────────────────────────────────
    case 'dashboard.kpis':
      return computeKpis();
    case 'dashboard.recentActivity':
      return recentActivity;
    case 'dashboard.weeklyStudy':
      return weeklyStudy;
    case 'dashboard.attendanceTrend':
      return attendanceTrend;
    case 'dashboard.performanceMix':
      return performanceMix;
    case 'dashboard.batchOverview':
      return batchOverview;
    case 'dashboard.upcomingTasks':
      return upcomingTasks;

    // ── Daily Tracker ─────────────────────────────────────────────────────
    case 'tracker.day': {
      const { dayIndex = 13, batch = 'All Batches' } = payload;
      const list = state.students
        .filter(s => batch === 'All Batches' || s.batch === batch)
        .map(s => ({
          id: s.id,
          name: s.name,
          avatar: s.avatar,
          batch: s.batch,
          entry: s.tracker[dayIndex],
        }));
      const submitted = list.filter(x => x.entry.submitted).length;
      const missed = list.length - submitted;
      const rate = list.length ? Math.round((submitted / list.length) * 100) : 0;
      const days = (state.students[0]?.tracker || []).map(d => d.date);
      return { list, submitted, missed, rate, days };
    }

    // ── Leaderboard ───────────────────────────────────────────────────────
    case 'leaderboard.list': {
      const mode = payload.mode || 'overall';
      return [...state.students]
        .map(s => ({ ...s, score: scoreForMode(s, mode) }))
        .sort((a, b) => b.score - a.score);
    }

    // ── Announcements ─────────────────────────────────────────────────────
    case 'announcements.list':
      return state.announcements;
    case 'announcements.create': {
      const item = {
        id: `ANN-${String(state.announcements.length + 1).padStart(3, '0')}`,
        title: payload.title,
        body: payload.body,
        audience: payload.audience || 'All Batches',
        date: new Date().toISOString().slice(0, 10),
        pinned: false,
        author: state.mentor.name,
      };
      state.announcements = [item, ...state.announcements];
      return item;
    }
    case 'announcements.togglePin': {
      state.announcements = state.announcements.map(a =>
        a.id === payload.id ? { ...a, pinned: !a.pinned } : a
      );
      return { ok: true };
    }

    // ── Reports ───────────────────────────────────────────────────────────
    case 'reports.batch':
      return batchOverview;
    case 'reports.students':
      return state.students.map(s => ({
        id: s.id, name: s.name, avatar: s.avatar, batch: s.batch,
        attendance: s.attendance, studyHours: s.studyHours,
        submissionRate: s.submissionRate,
      }));

    // ── Mentor / Settings ─────────────────────────────────────────────────
    case 'mentor.get':
      return state.mentor;
    case 'mentor.update':
      state.mentor = { ...state.mentor, ...payload };
      return state.mentor;
    case 'notifications.get':
      return state.notifications;
    case 'notifications.update':
      state.notifications = { ...state.notifications, ...payload };
      return state.notifications;

    default:
      throw new Error(`Unknown action: ${action}`);
  }
}
