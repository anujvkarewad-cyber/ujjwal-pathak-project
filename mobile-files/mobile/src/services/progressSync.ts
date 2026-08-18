// Mentor analytics progress sync (consent-gated, summaries only).
//
// Two endpoints on the mentor (FastAPI) backend:
//   POST /api/consent        — turn sharing ON/OFF for this student
//   POST /api/progress-sync  — upload allowlisted per-chapter MCQ summaries
//
// Privacy: only chapter-level summary fields are sent (chapterId, masteryBand,
// attemptCount, accuracyRange, lastActivityDate, weakConceptTags). Raw answers,
// question text and per-question history NEVER leave the device.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { config } from '../config';
import { hmacSha256 } from './hmacSha256';
import type { EnrichedMcqQuestion } from '../data/mcqMetadata';

export type ProgressSummary = {
  studentId: string;
  chapterId: string;
  masteryBand: string;
  attemptCount: number;
  accuracyRange: string;
  lastActivityDate: string;
  weakConceptTags: string[];
};

export type ProgressTrendPoint = {
  weekStart: string;
  chapterId: string;
  masteryBand: string;
  attemptCount: number;
  accuracyRange: string;
};

const CONSENT_KEY = 'ump_mentor_share_progress_v1';

export const getShareChoice = async (studentId: string): Promise<boolean> => {
  try {
    const raw = await AsyncStorage.getItem(`${CONSENT_KEY}:${studentId}`);
    return raw === '1';
  } catch {
    return false;
  }
};

export const storeShareChoice = async (studentId: string, on: boolean) => {
  try {
    if (on) await AsyncStorage.setItem(`${CONSENT_KEY}:${studentId}`, '1');
    else await AsyncStorage.removeItem(`${CONSENT_KEY}:${studentId}`);
  } catch {
    /* best-effort local flag */
  }
};

export const setMentorSharing = async (studentId: string, sharing: boolean): Promise<void> => {
  const response = await fetch(`${config.mentorApiUrl}/api/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ studentId, sharing, device: `android-v${config.appVersion || '1.10.2'}` }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(`Could not ${sharing ? 'enable' : 'disable'} sharing (${response.status}). ${body?.detail || ''}`.trim());
  }
  await storeShareChoice(studentId, sharing);
};

export const syncToken = (studentId: string): string => hmacSha256(config.mentorSyncSecret, studentId);

// ── Aggregation ────────────────────────────────────────────────────────────

const accuracyToBand = (accuracy: number): string => {
  if (accuracy >= 85) return 'Mastered';
  if (accuracy >= 70) return 'Strong';
  if (accuracy >= 50) return 'Medium';
  return 'Weak';
};

const accuracyToRange = (accuracy: number): string => {
  if (accuracy >= 85) return '85-100';
  if (accuracy >= 70) return '70-84';
  if (accuracy >= 50) return '50-69';
  return '0-49';
};

type Session = {
  questionIds: string[];
  answers: Record<string, number>;
  completedAt?: number;
  date?: string;
};

const mondayOf = (timestamp: number): string => {
  const date = new Date(timestamp);
  const day = (date.getDay() + 6) % 7; // Monday = 0
  const start = new Date(date);
  start.setDate(date.getDate() - day);
  start.setHours(0, 0, 0, 0);
  return start.toISOString().slice(0, 10);
};

const localDay = (timestamp: number): string => {
  const date = new Date(timestamp);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

type AnswerEvent = {
  chapterId: string;
  subject: string;
  chapterTitle: string;
  correct: boolean;
  ts: number;
};

export const buildProgressPayload = (
  studentId: string,
  sessions: Session[],
  questionLookup: Map<string, EnrichedMcqQuestion>,
) => {
  const events: AnswerEvent[] = [];
  for (const session of sessions) {
    if (!session.completedAt) continue;
    for (const questionId of session.questionIds) {
      const answer = session.answers[questionId];
      if (answer === undefined || answer === null) continue;
      const question = questionLookup.get(questionId);
      if (!question?.chapterId) continue;
      events.push({
        chapterId: question.chapterId,
        subject: question.subject,
        chapterTitle: question.chapterTitle || question.chapter || question.subject,
        correct: answer === question.answer,
        ts: session.completedAt,
      });
    }
  }
  if (!events.length) return { summaries: [] as ProgressSummary[], trend: [] as ProgressTrendPoint[] };

  // Per-chapter summary
  const byChapter = new Map<string, { correct: number; answered: number; lastTs: number; subject: string; chapterTitle: string }>();
  for (const event of events) {
    const bucket = byChapter.get(event.chapterId) || { correct: 0, answered: 0, lastTs: 0, subject: event.subject, chapterTitle: event.chapterTitle };
    bucket.correct += event.correct ? 1 : 0;
    bucket.answered += 1;
    bucket.lastTs = Math.max(bucket.lastTs, event.ts);
    byChapter.set(event.chapterId, bucket);
  }

  const summaries: ProgressSummary[] = [];
  for (const [chapterId, bucket] of byChapter) {
    const accuracy = bucket.answered ? (bucket.correct / bucket.answered) * 100 : 0;
    summaries.push({
      studentId,
      chapterId,
      masteryBand: accuracyToBand(accuracy),
      attemptCount: bucket.answered,
      accuracyRange: accuracyToRange(accuracy),
      lastActivityDate: localDay(bucket.lastTs),
      weakConceptTags: accuracy < 50 ? [bucket.subject, bucket.chapterTitle].filter(Boolean).slice(0, 8) : [],
    });
  }

  // Per-chapter weekly trend (drives improvement / at-risk analytics)
  const trend: ProgressTrendPoint[] = [];
  const weekByChapter = new Map<string, Map<string, { correct: number; answered: number }>>();
  for (const event of events) {
    const week = mondayOf(event.ts);
    const weeks = weekByChapter.get(event.chapterId) || new Map<string, { correct: number; answered: number }>();
    const bucket = weeks.get(week) || { correct: 0, answered: 0 };
    bucket.correct += event.correct ? 1 : 0;
    bucket.answered += 1;
    weeks.set(week, bucket);
    weekByChapter.set(event.chapterId, weeks);
  }
  for (const [chapterId, weeks] of weekByChapter) {
    const sorted = [...weeks.keys()].sort().slice(-12);
    for (const week of sorted) {
      const bucket = weeks.get(week)!;
      const accuracy = bucket.answered ? (bucket.correct / bucket.answered) * 100 : 0;
      trend.push({
        weekStart: week,
        chapterId,
        masteryBand: accuracyToBand(accuracy),
        attemptCount: bucket.answered,
        accuracyRange: accuracyToRange(accuracy),
      });
    }
  }
  // Keep the same 94-chapter cap as the backend; sort summaries by chapterId.
  summaries.sort((a, b) => a.chapterId.localeCompare(b.chapterId));
  return { summaries: summaries.slice(0, 94), trend };
};

export const syncProgress = async (studentId: string, summaries: ProgressSummary[], trend: ProgressTrendPoint[]): Promise<{ ok: boolean; accepted?: number }> => {
  if (!summaries.length) return { ok: true, accepted: 0 };
  const response = await fetch(`${config.mentorApiUrl}/api/progress-sync`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Sync-Token': syncToken(studentId),
    },
    body: JSON.stringify({ studentId, summaries, trend }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 403) return { ok: false }; // sharing disabled — silence
    throw new Error(`Progress sync failed (${response.status}). ${body?.detail || ''}`.trim());
  }
  const result = await response.json();
  return { ok: true, accepted: result?.accepted?.summaries ?? summaries.length };
};
