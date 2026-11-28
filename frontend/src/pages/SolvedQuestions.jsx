import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bell,
  BookOpenCheck,
  CalendarOff,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  FileText,
  Filter,
  PlaneTakeoff,
  RefreshCw,
  RotateCcw,
  Search,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  useRemindSolvedQuestions,
  useSendFeedback,
  useSolvedQuestionsReport,
} from '@/api/hooks';
import {
  SOLVED_QUESTION_SUBJECTS,
  resolveMentorProofUrl,
} from '@/api/tracker';
import SheetSourceStatus from '@/components/common/SheetSourceStatus';
import { Skeleton } from '@/components/common/Skeleton';
import StudentAccessToggle from '@/components/students/StudentAccessToggle';
import { cn } from '@/utils/format';
import { TRACKER_GROUP_FILTERS } from '@/utils/studentGroup';

const IST_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

function isoTodayIndia() {
  const parts = Object.fromEntries(
    IST_FORMATTER.formatToParts(new Date()).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function shiftIsoDay(iso, deltaDays) {
  const [y, m, d] = String(iso || '').split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + deltaDays);
  return dt.toISOString().slice(0, 10);
}

function csvEscape(value) {
  let text = String(value ?? '');
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

const SUBJECT_BADGE_STYLE = {
  Accounts: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30',
  Law: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:border-violet-500/30',
  DT: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30',
  GST: 'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-500/10 dark:text-teal-300 dark:border-teal-500/30',
  Costing: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30',
  Audit: 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-300 dark:border-indigo-500/30',
  FM: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-500/10 dark:text-cyan-300 dark:border-cyan-500/30',
  SM: 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200 dark:bg-fuchsia-500/10 dark:text-fuchsia-300 dark:border-fuchsia-500/30',
};

export default function SolvedQuestions({ scopedBatch, scopedGroup } = {}) {
  const today = useMemo(() => isoTodayIndia(), []);
  const [preset, setPreset] = useState('today');
  const [fromDate, setFromDate] = useState(today);
  const [toDate, setToDate] = useState(today);
  const [batch, setBatch] = useState(scopedBatch || 'All Batches');
  const [group, setGroup] = useState(scopedGroup || 'All Groups');
  const [subject, setSubject] = useState('All Subjects');
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');

  const [remindModalOpen, setRemindModalOpen] = useState(false);
  const [remindTargets, setRemindTargets] = useState([]);
  const [remindMessage, setRemindMessage] = useState('');

  const [feedbackStudent, setFeedbackStudent] = useState(null);
  const [feedbackText, setFeedbackText] = useState('');

  const effectiveBatch = scopedBatch || batch;
  const effectiveGroup = scopedGroup || group;

  const {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useSolvedQuestionsReport({
    from: fromDate,
    to: toDate,
    batch: effectiveBatch,
    group: effectiveGroup,
    subject,
  });

  const remindMutation = useRemindSolvedQuestions();
  const sendFeedbackMutation = useSendFeedback();

  const applyPreset = (nextPreset) => {
    setPreset(nextPreset);
    if (nextPreset === 'today') {
      setFromDate(today);
      setToDate(today);
    } else if (nextPreset === 'yesterday') {
      const y = shiftIsoDay(today, -1);
      setFromDate(y);
      setToDate(y);
    } else if (nextPreset === 'last7') {
      setFromDate(shiftIsoDay(today, -6));
      setToDate(today);
    }
  };

  const batchOptions = useMemo(() => {
    const raw = data?.batches || ['All Batches'];
    if (effectiveBatch && !raw.includes(effectiveBatch)) {
      return [...raw, effectiveBatch];
    }
    return raw;
  }, [data?.batches, effectiveBatch]);

  const expectedRows = useMemo(
    () => (data?.items || []).filter((item) => !item.notExpected),
    [data?.items],
  );

  const nonSubmittingRows = useMemo(
    () => expectedRows.filter((item) => item.status === 'not_submitted'),
    [expectedRows],
  );

  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return expectedRows.filter((row) => {
      if (statusFilter === 'submitted' && row.status !== 'submitted') return false;
      if (statusFilter === 'not_submitted' && row.status !== 'not_submitted') return false;
      if (
        statusFilter === 'logged_only' &&
        row.status !== 'logged_only' &&
        row.status !== 'logged_other'
      ) {
        return false;
      }
      if (statusFilter === 'excused' && row.status !== 'leave' && row.status !== 'absent') {
        return false;
      }
      if (q) {
        const hay = `${row.studentId} ${row.studentName} ${row.batch} ${row.group}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [expectedRows, statusFilter, search]);

  const summary = data?.summary || {
    expectedCount: 0,
    submittedCount: 0,
    submittedSolvedCount: 0,
    loggedOnlyCount: 0,
    notSubmittedCount: 0,
    excusedCount: 0,
    submissionRate: 0,
    totalQuestionsSolved: 0,
    totalSheetsUploaded: 0,
  };

  const openBulkRemind = (targets) => {
    if (!targets.length) {
      toast.info('Everyone expected in this view has already submitted.');
      return;
    }
    const subjLabel = subject !== 'All Subjects' ? `${subject} ` : 'subject-wise ';
    const dateLabel = fromDate === toDate ? fromDate : `${fromDate} to ${toDate}`;
    setRemindTargets(targets);
    setRemindMessage(
      `Reminder: Please submit your ${subjLabel}solved questions & practice sheet (${dateLabel}) in your Daily Study Log.`,
    );
    setRemindModalOpen(true);
  };

  const handleConfirmRemind = async () => {
    if (!remindTargets.length) return;
    try {
      const res = await remindMutation.mutateAsync({
        studentIds: remindTargets.map((r) => r.studentId),
        date: toDate,
        subject: subject !== 'All Subjects' ? subject : undefined,
        message: remindMessage.trim(),
      });
      toast.success(
        `Sent push + in-app reminder to ${res?.remindedCount ?? remindTargets.length} student(s).`,
      );
      setRemindModalOpen(false);
      setRemindTargets([]);
    } catch (err) {
      toast.error(err?.message || 'Could not send reminders.');
    }
  };

  const exportCsv = () => {
    if (!visibleRows.length) {
      toast.info('No rows to export.');
      return;
    }
    const headers = [
      'Student ID',
      'Student Name',
      'Batch',
      'Group',
      'Status',
      'Hours',
      'Total Solved',
      ...SOLVED_QUESTION_SUBJECTS,
      'Sheet / Topics',
      'Proof / Sheet Links',
    ];
    const lines = [headers.map(csvEscape).join(',')];
    visibleRows.forEach((row) => {
      const sheetNotes = (row.sheets || [])
        .filter((s) => s.subject !== 'Daily Proof' && s.sheetName)
        .map((s) => `${s.subject}: ${s.sheetName}`)
        .join(' | ');
      const proofLinks = Array.from(
        new Set(
          (row.sheets || [])
            .map((s) => resolveMentorProofUrl(s.mentorProofUrl || s.proofUrl))
            .filter(Boolean),
        ),
      ).join(' | ');
      const vals = [
        row.studentId,
        row.studentName,
        row.batch,
        row.group,
        row.status,
        row.hours,
        row.totalSolved,
        ...SOLVED_QUESTION_SUBJECTS.map((subj) => row.bySubject?.[subj] ?? 0),
        sheetNotes,
        proofLinks,
      ];
      lines.push(vals.map(csvEscape).join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `solved-questions-${fromDate}-to-${toDate}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const hasCustomFilters =
    (!scopedBatch && batch !== 'All Batches') ||
    (!scopedGroup && group !== 'All Groups') ||
    subject !== 'All Subjects' ||
    statusFilter !== 'all' ||
    Boolean(search.trim());

  return (
    <div className="space-y-6" data-testid="solved-questions-page">
      {data?.sources && <SheetSourceStatus source={data.sources} />}

      {/* KPI Summary Strip */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <button
          type="button"
          onClick={() => setStatusFilter(statusFilter === 'submitted' ? 'all' : 'submitted')}
          className={cn(
            'text-left bg-white dark:bg-slate-900 border rounded-xl p-5 transition-colors',
            statusFilter === 'submitted'
              ? 'border-emerald-500 ring-2 ring-emerald-500/20'
              : 'border-slate-200 dark:border-slate-800 hover:border-emerald-300',
          )}
          data-testid="sq-kpi-submitted"
        >
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
            Submitted Solved Qs
          </div>
          <div className="mt-2 font-heading text-3xl font-bold text-emerald-600 dark:text-emerald-400">
            {isLoading ? '—' : summary.submittedSolvedCount}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">
            {isLoading ? '' : `${summary.submissionRate}% overall tracker rate`}
          </div>
        </button>

        <button
          type="button"
          onClick={() => setStatusFilter(statusFilter === 'not_submitted' ? 'all' : 'not_submitted')}
          className={cn(
            'text-left bg-white dark:bg-slate-900 border rounded-xl p-5 transition-colors',
            statusFilter === 'not_submitted'
              ? 'border-rose-500 ring-2 ring-rose-500/20'
              : 'border-slate-200 dark:border-slate-800 hover:border-rose-300',
          )}
          data-testid="sq-kpi-not-submitted"
        >
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
            Not Submitted
          </div>
          <div className="mt-2 font-heading text-3xl font-bold text-rose-600 dark:text-rose-400">
            {isLoading ? '—' : summary.notSubmittedCount}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">Tap to view defaulters</div>
        </button>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
            Total Questions Solved
          </div>
          <div className="mt-2 font-heading text-3xl font-bold text-[#2563EB]" data-testid="sq-kpi-total-questions">
            {isLoading ? '—' : summary.totalQuestionsSolved}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">
            {subject === 'All Subjects' ? 'Across all 8 CA subjects' : `In ${subject}`}
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
            Sheets / Proofs Uploaded
          </div>
          <div className="mt-2 font-heading text-3xl font-bold text-indigo-600 dark:text-indigo-400" data-testid="sq-kpi-sheets">
            {isLoading ? '—' : summary.totalSheetsUploaded}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">PDF &amp; photo sheets attached</div>
        </div>

        <button
          type="button"
          onClick={() => setStatusFilter(statusFilter === 'excused' ? 'all' : 'excused')}
          className={cn(
            'text-left bg-white dark:bg-slate-900 border rounded-xl p-5 transition-colors',
            statusFilter === 'excused'
              ? 'border-amber-500 ring-2 ring-amber-500/20'
              : 'border-slate-200 dark:border-slate-800 hover:border-amber-300',
          )}
        >
          <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
            Leave / Absent
          </div>
          <div className="mt-2 font-heading text-3xl font-bold text-amber-600 dark:text-amber-400">
            {isLoading ? '—' : summary.excusedCount}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">Excluded from defaulters</div>
        </button>
      </div>

      {/* 8-Subject Breakdown Cards (DT & GST strictly separate) */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <BookOpenCheck className="w-4 h-4 text-[#2563EB]" />
            <h3 className="font-heading font-bold text-sm text-slate-900 dark:text-white">
              Subject-Wise Solved Questions (DT &amp; GST Separate)
            </h3>
          </div>
          {subject !== 'All Subjects' && (
            <button
              type="button"
              onClick={() => setSubject('All Subjects')}
              className="text-xs font-semibold text-[#2563EB] hover:underline"
            >
              Show all 8 subjects
            </button>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2.5">
          {(data?.subjectTotals || SOLVED_QUESTION_SUBJECTS.map((s) => ({ subject: s, questionsSolved: 0, studentsSubmitted: 0, group: '' }))).map(
            (card) => {
              const active = subject === card.subject;
              const groupTag = card.group === 'group1' ? 'G1' : card.group === 'group2' ? 'G2' : '';
              return (
                <button
                  key={card.subject}
                  type="button"
                  data-testid={`sq-subject-card-${card.subject}`}
                  onClick={() => setSubject(active ? 'All Subjects' : card.subject)}
                  className={cn(
                    'rounded-xl border p-3 text-left transition-all',
                    active
                      ? 'border-[#2563EB] bg-blue-50/70 dark:bg-blue-500/15 ring-2 ring-blue-500/20'
                      : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700',
                  )}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-heading font-bold text-xs text-slate-900 dark:text-white">
                      {card.subject}
                    </span>
                    {groupTag && (
                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                        {groupTag}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 font-heading text-xl font-bold text-[#2563EB]">
                    {isLoading ? '—' : card.questionsSolved}
                  </div>
                  <div className="text-[11px] text-slate-500 dark:text-slate-400">
                    {isLoading ? '' : `${card.studentsSubmitted} student${card.studentsSubmitted === 1 ? '' : 's'}`}
                  </div>
                </button>
              );
            },
          )}
        </div>
      </div>

      {error && (
        <div
          className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200"
          role="alert"
        >
          Could not load solved questions report: {error.message || 'Please try again.'}
        </div>
      )}

      {/* Main Filter Bar + Table */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 space-y-4">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="inline-flex rounded-lg bg-slate-100 dark:bg-slate-800 p-1">
              {[
                ['today', 'Today'],
                ['yesterday', 'Yesterday'],
                ['last7', 'Last 7 Days'],
                ['custom', 'Custom'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => applyPreset(key)}
                  className={cn(
                    'px-3 py-1.5 rounded-md text-xs font-semibold transition-colors',
                    preset === key
                      ? 'bg-white dark:bg-slate-900 text-[#2563EB] shadow-sm'
                      : 'text-slate-600 dark:text-slate-300',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              From
              <input
                type="date"
                value={fromDate}
                max={toDate}
                onChange={(e) => {
                  setPreset('custom');
                  setFromDate(e.target.value);
                }}
                className="h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 text-xs text-slate-700 dark:text-slate-200"
              />
            </label>
            <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              To
              <input
                type="date"
                value={toDate}
                min={fromDate}
                max={today}
                onChange={(e) => {
                  setPreset('custom');
                  setToDate(e.target.value);
                }}
                className="h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 text-xs text-slate-700 dark:text-slate-200"
              />
            </label>

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <button
                type="button"
                data-testid="sq-remind-defaulters"
                onClick={() => openBulkRemind(nonSubmittingRows)}
                disabled={isLoading || nonSubmittingRows.length === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-rose-600 px-3.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                <Bell className="w-3.5 h-3.5" />
                Remind Non-Submitters ({nonSubmittingRows.length})
              </button>
              <button
                type="button"
                onClick={exportCsv}
                disabled={isLoading || visibleRows.length === 0}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 px-3 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
              >
                <Download className="w-3.5 h-3.5" />
                Export CSV
              </button>
              <button
                type="button"
                onClick={() => refetch()}
                disabled={isFetching}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 px-3 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', isFetching && 'animate-spin')} />
                Refresh
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Filter className="w-4 h-4 text-slate-400" />
            <label className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-slate-500">Batch</span>
              <select
                disabled={Boolean(scopedBatch)}
                value={effectiveBatch}
                onChange={(e) => setBatch(e.target.value)}
                className="h-9 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-slate-700 dark:text-slate-200"
              >
                {batchOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-slate-500">Group</span>
              <select
                disabled={Boolean(scopedGroup)}
                value={effectiveGroup}
                onChange={(e) => setGroup(e.target.value)}
                className="h-9 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-slate-700 dark:text-slate-200"
              >
                {TRACKER_GROUP_FILTERS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-slate-500">Subject</span>
              <select
                data-testid="sq-subject-select"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="h-9 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-slate-700 dark:text-slate-200"
              >
                <option value="All Subjects">All 8 Subjects</option>
                {SOLVED_QUESTION_SUBJECTS.map((subj) => (
                  <option key={subj} value={subj}>
                    {subj}
                  </option>
                ))}
              </select>
            </label>

            <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-800 p-0.5 text-xs">
              {[
                ['all', `All (${expectedRows.length})`],
                ['not_submitted', `Not Submitted (${summary.notSubmittedCount})`],
                ['submitted', `Submitted (${summary.submittedSolvedCount})`],
                ['logged_only', `Logged Only (${summary.loggedOnlyCount})`],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setStatusFilter(key)}
                  className={cn(
                    'px-2.5 py-1.5 rounded-md font-semibold transition-colors',
                    statusFilter === key
                      ? 'bg-[#2563EB] text-white'
                      : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="relative ml-auto min-w-[200px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search student or UMP ID…"
                className="h-9 w-full pl-8 pr-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
              />
            </div>

            {hasCustomFilters && (
              <button
                type="button"
                onClick={() => {
                  if (!scopedBatch) setBatch('All Batches');
                  if (!scopedGroup) setGroup('All Groups');
                  setSubject('All Subjects');
                  setStatusFilter('all');
                  setSearch('');
                }}
                className="inline-flex h-9 items-center gap-1 rounded-lg px-2.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Reset
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                <th className="px-5 py-3">Student</th>
                <th className="px-5 py-3">Cohort</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Questions Solved</th>
                <th className="px-5 py-3">Subject-Wise Breakdown (DT &amp; GST Separate)</th>
                <th className="px-5 py-3">Uploaded Sheets / Proof</th>
                <th className="px-5 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading &&
                Array.from({ length: 5 }).map((_, idx) => (
                  <tr key={idx} className="border-b border-slate-100 dark:border-slate-800">
                    <td colSpan={7} className="px-5 py-3">
                      <Skeleton className="h-9 w-full" />
                    </td>
                  </tr>
                ))}

              {!isLoading &&
                visibleRows.map((row) => {
                  const activeSubjects = SOLVED_QUESTION_SUBJECTS.filter(
                    (subj) => (row.bySubject?.[subj] || 0) > 0,
                  );
                  const topicNotes = (row.sheets || []).filter(
                    (s) => s.subject !== 'Daily Proof' && s.sheetName,
                  );
                  const proofItems = (row.sheets || []).filter((s) =>
                    Boolean(resolveMentorProofUrl(s.mentorProofUrl || s.proofUrl)),
                  );

                  return (
                    <tr
                      key={row.studentId}
                      data-testid={`sq-row-${row.studentId}`}
                      className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors"
                    >
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-slate-900 dark:text-white">
                          <Link
                            to={`/students/${row.studentId}`}
                            className="hover:text-[#2563EB] underline-offset-2 hover:underline"
                          >
                            {row.studentName}
                          </Link>
                        </div>
                        <div className="text-xs text-slate-500">{row.studentId}</div>
                      </td>

                      <td className="px-5 py-3.5">
                        <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                          {row.batch}
                        </div>
                        <span className="mt-1 inline-flex rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                          {row.group}
                        </span>
                      </td>

                      <td className="px-5 py-3.5">
                        {row.status === 'submitted' && (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Submitted
                          </span>
                        )}
                        {(row.status === 'logged_only' || row.status === 'logged_other') && (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 dark:bg-blue-500/10 px-2.5 py-1 text-xs font-semibold text-blue-700 dark:text-blue-300">
                            <Clock className="w-3.5 h-3.5" />
                            {row.status === 'logged_other'
                              ? `Logged other (${row.hours}h)`
                              : `Logged (${row.hours}h · no Q count)`}
                          </span>
                        )}
                        {row.status === 'not_submitted' && (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 dark:bg-rose-500/10 px-2.5 py-1 text-xs font-semibold text-rose-700 dark:text-rose-400">
                            <XCircle className="w-3.5 h-3.5" />
                            Not Submitted
                          </span>
                        )}
                        {row.status === 'leave' && (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 dark:bg-blue-500/10 px-2.5 py-1 text-xs font-semibold text-[#2563EB]">
                            <PlaneTakeoff className="w-3.5 h-3.5" />
                            On Leave
                          </span>
                        )}
                        {row.status === 'absent' && (
                          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 dark:bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-700 dark:text-amber-300">
                            <CalendarOff className="w-3.5 h-3.5" />
                            Absent
                          </span>
                        )}
                        {fromDate !== toDate && (
                          <div className="mt-1 text-[11px] text-slate-400">
                            {row.submittedDays}/{row.expectedDays}d submitted
                          </div>
                        )}
                      </td>

                      <td className="px-5 py-3.5">
                        <div className="font-heading text-base font-bold text-slate-900 dark:text-white">
                          {row.totalSolved} Qs
                        </div>
                        <div className="text-xs text-slate-500">{row.hours}h studied</div>
                      </td>

                      <td className="px-5 py-3.5 max-w-md">
                        {activeSubjects.length > 0 ? (
                          <div className="space-y-1.5">
                            <div className="flex flex-wrap gap-1.5">
                              {activeSubjects.map((subj) => (
                                <span
                                  key={subj}
                                  className={cn(
                                    'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold',
                                    SUBJECT_BADGE_STYLE[subj] ||
                                      'bg-slate-100 text-slate-700 border-slate-200',
                                  )}
                                >
                                  <span>{subj}:</span>
                                  <span className="font-bold">{row.bySubject[subj]}</span>
                                </span>
                              ))}
                            </div>
                            {topicNotes.length > 0 && (
                              <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate" title={topicNotes.map((t) => `${t.subject}: ${t.sheetName}`).join(' · ')}>
                                {topicNotes.map((t) => `${t.subject}: ${t.sheetName}`).join(' · ')}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-5 py-3.5">
                        {proofItems.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {proofItems.slice(0, 4).map((sheet, sIdx) => {
                              const href = resolveMentorProofUrl(
                                sheet.mentorProofUrl || sheet.proofUrl,
                              );
                              const label =
                                sheet.subject === 'Daily Proof'
                                  ? 'Daily Sheet'
                                  : `${sheet.subject} Sheet`;
                              return (
                                <a
                                  key={`${sheet.date}-${sheet.subject}-${sIdx}`}
                                  href={href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-blue-700"
                                >
                                  <FileText className="w-3 h-3" />
                                  {label}
                                  <ExternalLink className="w-3 h-3 opacity-80" />
                                </a>
                              );
                            })}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">No sheet</span>
                        )}
                      </td>

                      <td className="px-5 py-3.5">
                        <div className="flex flex-wrap items-center gap-2">
                          {row.status === 'not_submitted' && (
                            <button
                              type="button"
                              onClick={() => openBulkRemind([row])}
                              className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-rose-700"
                            >
                              <Bell className="w-3 h-3" />
                              Remind
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              setFeedbackStudent(row);
                              setFeedbackText('');
                            }}
                            className="inline-flex items-center rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700"
                          >
                            Feedback
                          </button>
                          <StudentAccessToggle
                            studentId={row.studentId}
                            studentName={row.studentName}
                            enabled={row.accessEnabled !== false}
                            known
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}

              {!isLoading && visibleRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center">
                    <div className="font-semibold text-slate-700 dark:text-slate-200">
                      No students match these filters
                    </div>
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      Change the status tab, subject filter, or search text to view more students.
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bulk / Single Reminder Confirmation Modal */}
      {remindModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4">
            <h2 className="font-heading text-lg font-bold text-slate-900 dark:text-white">
              Remind {remindTargets.length} Student{remindTargets.length === 1 ? '' : 's'}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Sends both a live mobile/web push notification and an in-app Mentor Reminder to{' '}
              {remindTargets.length === 1
                ? `${remindTargets[0].studentName} (${remindTargets[0].studentId})`
                : `${remindTargets.length} non-submitting students`}
              .
            </p>
            <textarea
              rows={4}
              value={remindMessage}
              onChange={(e) => setRemindMessage(e.target.value)}
              className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 p-3 text-sm text-slate-800 dark:text-slate-100 outline-none focus:border-[#2563EB]"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRemindModalOpen(false)}
                className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={remindMutation.isPending || !remindMessage.trim()}
                onClick={handleConfirmRemind}
                className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {remindMutation.isPending ? 'Sending…' : `Send Reminder (${remindTargets.length})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Direct Mentor Feedback Modal */}
      {feedbackStudent && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4">
            <h2 className="font-heading text-lg font-bold text-slate-900 dark:text-white">
              Send Feedback to {feedbackStudent.studentName}
            </h2>
            <textarea
              rows={4}
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="Write feedback on their solved questions or practice sheet…"
              className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 p-3 text-sm text-slate-800 dark:text-slate-100 outline-none focus:border-[#2563EB]"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setFeedbackStudent(null)}
                className="rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={sendFeedbackMutation.isPending || !feedbackText.trim()}
                onClick={async () => {
                  try {
                    await sendFeedbackMutation.mutateAsync({
                      studentId: feedbackStudent.studentId,
                      message: feedbackText.trim(),
                      priority: 'Normal',
                    });
                    toast.success(`Feedback sent to ${feedbackStudent.studentName}.`);
                    setFeedbackStudent(null);
                  } catch (err) {
                    toast.error(err?.message || 'Could not send feedback.');
                  }
                }}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {sendFeedbackMutation.isPending ? 'Sending…' : 'Send Feedback'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
