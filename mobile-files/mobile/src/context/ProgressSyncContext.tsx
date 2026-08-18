import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { dailyMcqBank } from '../data/dailyMcqBank';
import { enrichMcqQuestion, EnrichedMcqQuestion } from '../data/mcqMetadata';
import { buildProgressPayload, getShareChoice, setMentorSharing, syncProgress, ProgressSummary, ProgressTrendPoint } from '../services/progressSync';
import { useAuth } from './AuthContext';
import { useDailyMcq } from './DailyMcqContext';
import { useMcqBank } from './McqBankContext';
import { useMcqPractice } from './McqPracticeContext';

export type ProgressSyncStatus = 'idle' | 'off' | 'syncing' | 'ok' | 'error';

type ProgressSyncValue = {
  sharing: boolean;
  status: ProgressSyncStatus;
  lastSyncedAt?: string;
  setSharing: (on: boolean) => Promise<void>;
  syncNow: () => Promise<void>;
};

const ProgressSyncContext = createContext<ProgressSyncValue | undefined>(undefined);

export const ProgressSyncProvider = ({ children }: PropsWithChildren) => {
  const { student, backendMode } = useAuth();
  const { history: dailyHistory } = useDailyMcq();
  const { history: practiceHistory } = useMcqPractice();
  const { questions: liveQuestions } = useMcqBank();
  const [sharing, setSharingState] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<ProgressSyncStatus>('idle');
  const [lastSyncedAt, setLastSyncedAt] = useState<string>();
  const syncingRef = useRef(false);

  // Build a lookup from every available question id to its chapter metadata.
  const questionLookup = useMemo<Map<string, EnrichedMcqQuestion>>(() => {
    const lookup = new Map<string, EnrichedMcqQuestion>();
    for (const question of liveQuestions) if (question?.id) lookup.set(question.id, question);
    for (const question of dailyMcqBank) {
      try {
        const enriched = enrichMcqQuestion(question);
        if (enriched?.id && !lookup.has(enriched.id)) lookup.set(enriched.id, enriched);
      } catch { /* bundled preview bank may have unmapped ids — ignore */ }
    }
    return lookup;
  }, [liveQuestions]);

  // Restore the student's saved sharing choice.
  useEffect(() => {
    let mounted = true;
    if (!student) {
      setLoaded(true);
      setSharingState(false);
      return;
    }
    getShareChoice(student.studentId).then((on) => {
      if (!mounted) return;
      setSharingState(on);
      setLoaded(true);
    });
    return () => { mounted = false; };
  }, [student]);

  const syncNow = useCallback(async () => {
    if (!student || backendMode === 'mock' || backendMode === 'live-readonly') return;
    if (!sharing) { setStatus('off'); return; }
    if (syncingRef.current) return;
    syncingRef.current = true;
    setStatus('syncing');
    try {
      const sessions = [
        ...dailyHistory.filter((attempt) => attempt.completedAt),
        ...practiceHistory.filter((session) => session.completedAt),
      ];
      const { summaries, trend } = buildProgressPayload(student.studentId, sessions, questionLookup);
      const result = await syncProgress(student.studentId, summaries, trend);
      if (result.ok) {
        setStatus('ok');
        setLastSyncedAt(new Date().toISOString());
        await AsyncStorage.setItem('ump_progress_synced_at', new Date().toISOString()).catch(() => undefined);
      } else {
        setStatus('off'); // 403 — sharing was revoked server-side
      }
    } catch {
      setStatus('error');
    } finally {
      syncingRef.current = false;
    }
  }, [backendMode, dailyHistory, practiceHistory, questionLookup, sharing, student]);

  // Auto-sync once a completed attempt exists while sharing is ON.
  const hasCompleted = (dailyHistory.some((a) => a.completedAt) || practiceHistory.some((s) => s.completedAt));
  useEffect(() => {
    if (!loaded || !student || sharing === false || !hasCompleted) return;
    if (backendMode === 'mock' || backendMode === 'live-readonly') return;
    const timer = setTimeout(() => { syncNow().catch(() => undefined); }, 800);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, sharing, hasCompleted, backendMode, student?.studentId]);

  const setSharing = useCallback(async (on: boolean) => {
    if (!student) return;
    setSharingState(on);
    if (backendMode === 'mock' || backendMode === 'live-readonly') return;
    try {
      await setMentorSharing(student.studentId, on);
      if (on) await syncNow();
    } catch {
      setStatus('error');
    }
  }, [backendMode, student, syncNow]);

  const value = useMemo<ProgressSyncValue>(() => ({ sharing, status, lastSyncedAt, setSharing, syncNow }), [lastSyncedAt, setSharing, sharing, status, syncNow]);

  return <ProgressSyncContext.Provider value={value}>{children}</ProgressSyncContext.Provider>;
};

export const useProgressSync = () => {
  const context = useContext(ProgressSyncContext);
  if (!context) throw new Error('useProgressSync must be used inside ProgressSyncProvider');
  return context;
};
