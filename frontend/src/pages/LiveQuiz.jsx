import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Layers, ListChecks, RefreshCw, Users } from 'lucide-react';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';
import { getLiveQuizPool, previewLiveQuiz } from '@/api/liveQuiz';
import { poolView, selectionView, warningKind, normaliseStudentIds } from '@/utils/liveQuizView';

// Live Quiz tab — two questions, in this order:
//   1. what is actually in the pool that students can be tested on right now (subject counts);
//   2. which question goes to which student for a given test id.
// (2) is not decoration: the student paper is sampled with `seed = f"{testId}:{studentId}"`, so two
// students in the same test never see the same paper. A flat question list cannot answer the mentor's
// question; a preview of the real sampler can. Everything here is read-only — approving/editing
// still happens in Question Review, and this tab never writes to the database.

const inputCls =
  'w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300 dark:focus:ring-slate-700';
const labelCls = 'block text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1';

function Stat({ label, value, tone = 'slate', hint }) {
  return (
    <div
      className={cn(
        'rounded-xl border px-4 py-3',
        tone === 'amber'
          ? 'border-amber-200 bg-amber-50 dark:border-amber-900/40 dark:bg-amber-900/10'
          : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
      )}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">{value}</div>
      {hint ? <div className="text-[11px] text-slate-500">{hint}</div> : null}
    </div>
  );
}

export default function LiveQuiz() {
  const [pool, setPool] = useState(null);
  const [poolErr, setPoolErr] = useState('');
  const [loading, setLoading] = useState(true);
  const [subject, setSubject] = useState('');

  const [testId, setTestId] = useState('live-quiz-01');
  const [chapters, setChapters] = useState('');
  const [count, setCount] = useState(10);
  const [idsText, setIdsText] = useState('');

  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [openStudent, setOpenStudent] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setPoolErr('');
    try {
      const data = await getLiveQuizPool();
      setPool(data);
      const first = data?.subjects?.[0]?.subject;
      if (first) setSubject((cur) => cur || first);
    } catch (e) {
      setPoolErr(e?.message || 'Pool load nahi ho paya — backend reachable hai?');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const view = useMemo(() => poolView(pool), [pool]);
  const sel = useMemo(() => selectionView(preview), [preview]);
  const studentIds = useMemo(() => normaliseStudentIds(idsText), [idsText]);

  const runPreview = useCallback(async () => {
    if (!subject || !testId.trim() || studentIds.length === 0) {
      setErr('Test ID, subject aur kam-se-kam ek student ID chahiye.');
      return;
    }
    setBusy(true);
    setErr('');
    try {
      const body = {
        testId: testId.trim(),
        subject,
        studentIds,
        count: Math.max(1, Number(count) || 1),
      };
      const list = chapters.split(',').map((s) => s.trim()).filter(Boolean);
      if (list.length) body.chapters = list;
      setPreview(await previewLiveQuiz(body));
      setOpenStudent(studentIds[0]);
    } catch (e) {
      setErr(e?.message || 'Preview fail ho gaya.');
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }, [chapters, count, studentIds, subject, testId]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
            <Layers className="h-5 w-5" /> Live Quiz pool
          </h2>
          <p className="text-sm text-slate-500">
            Jo questions students ko sach me mil sakte hain (approved / release_candidate / published).
            Read-only view — approve karne ke liye Question Review use karein.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} /> Refresh
        </button>
      </div>

      {poolErr ? (
        <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{poolErr}</span>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {loading ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[86px]" />)
        ) : (
          <>
            <Stat label="Selectable now" value={view.readable.toLocaleString('en-IN')} hint="in a live paper" />
            <Stat
              label="Needs review"
              value={view.needsReview.toLocaleString('en-IN')}
              tone={view.needsReview ? 'amber' : 'slate'}
              hint="not visible to students yet"
            />
            <Stat label="Total in pool" value={view.total.toLocaleString('en-IN')} />
            <Stat label="Subjects" value={view.subjects} hint={view.truncated ? 'scan capped — counts are a floor' : 'with questions'} />
          </>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        {/* 1 · kiske liye kitna data hai */}
        <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <ListChecks className="h-4 w-4 text-slate-500" />
            <h3 className="text-sm font-semibold">Pool by subject</h3>
            <span className="ml-auto text-[11px] text-slate-500">tap a row to select it</span>
          </header>
          {loading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9" />)}
            </div>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {view.rows.map((r) => (
                <li key={r.subject}>
                  <button
                    type="button"
                    onClick={() => setSubject(r.subject)}
                    className={cn(
                      'flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50',
                      subject === r.subject && 'bg-slate-50 dark:bg-slate-800/70',
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate font-medium text-slate-800 dark:text-slate-200">
                      {r.subject}
                    </span>
                    <span className="tabular-nums text-slate-600 dark:text-slate-300">{r.readable}</span>
                    {r.needsReview ? (
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                        {r.needsReview} review
                      </span>
                    ) : null}
                    {r.blocked ? (
                      <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[11px] font-medium text-rose-700 dark:bg-rose-900/40 dark:text-rose-200">
                        no usable Qs
                      </span>
                    ) : null}
                    <span className="hidden w-16 text-right text-[11px] tabular-nums text-slate-400 sm:block">
                      {r.chapters} labels
                    </span>
                  </button>
                  {r.topChapters.length ? (
                    <div className="px-4 pb-2.5 text-[11px] text-slate-500">{r.topChapters.join(' · ')}</div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 2 · kaunsa question kis student ko */}
        <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <Users className="h-4 w-4 text-slate-500" />
            <h3 className="text-sm font-semibold">Who gets which question</h3>
            <span className="ml-auto text-[11px] text-slate-500">seed = testId : studentId</span>
          </header>

          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="lq-test">Test ID</label>
              <input id="lq-test" className={inputCls} value={testId} onChange={(e) => setTestId(e.target.value)} />
            </div>
            <div>
              <label className={labelCls} htmlFor="lq-subject">Subject</label>
              <select id="lq-subject" className={inputCls} value={subject} onChange={(e) => setSubject(e.target.value)}>
                {view.rows.map((r) => (
                  <option key={r.subject} value={r.subject}>
                    {r.subject} ({r.readable})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="lq-count">Questions per student</label>
              <input
                id="lq-count"
                type="number"
                min="1"
                max="500"
                className={inputCls}
                value={count}
                onChange={(e) => setCount(e.target.value)}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="lq-chapters">Chapters (optional, comma separated)</label>
              <input
                id="lq-chapters"
                className={inputCls}
                placeholder="Case 27, Mtp 8 Case Study 1"
                value={chapters}
                onChange={(e) => setChapters(e.target.value)}
              />
            </div>
            <div className="sm:col-span-2">
              <label className={labelCls} htmlFor="lq-ids">Student IDs (one per line)</label>
              <textarea
                id="lq-ids"
                rows={3}
                className={inputCls}
                placeholder={'240134\n240135\n240136'}
                value={idsText}
                onChange={(e) => setIdsText(e.target.value)}
              />
              <div className="mt-1 flex items-center gap-3">
                <span className="text-[11px] text-slate-500">{studentIds.length} student(s)</span>
                <button
                  type="button"
                  onClick={runPreview}
                  disabled={busy || loading}
                  className="ml-auto inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900"
                >
                  {busy ? <RefreshCw className="h-4 w-4 animate-spin" /> : null} Preview selection
                </button>
              </div>
            </div>
          </div>

          {err ? (
            <p className="px-4 pb-3 text-sm text-rose-700 dark:text-rose-300">{err}</p>
          ) : null}

          {!preview && !busy ? (
            <p className="px-4 pb-4 text-sm text-slate-500">
              Preview chalao to dekh sako ki har student ko kaun-kaun se question mil rahe hain — bilkul
              wahi selection jo app me chalti hai.
            </p>
          ) : null}

          {sel.warnings.length ? (
            <ul className="space-y-2 px-4 pb-3">
              {sel.warnings.map((w) => {
                const kind = warningKind(w);
                return (
                  <li
                    key={w.slice(0, 40)}
                    className={cn(
                      'flex items-start gap-2 rounded-lg border p-2.5 text-[12px]',
                      kind === 'empty'
                        ? 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-200'
                        : kind === 'fallback'
                          ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/40 dark:bg-amber-900/10 dark:text-amber-200'
                          : 'border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900/40 dark:bg-sky-900/10 dark:text-sky-200',
                    )}
                  >
                    {kind === 'info' ? <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                    <span>{w}</span>
                  </li>
                );
              })}
            </ul>
          ) : null}

          {sel.papers.length ? (
            <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-800">
              <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-slate-600 dark:text-slate-300">
                <span className="inline-flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                  {sel.perStudentCount} Qs/student · {sel.distinctQuestions} distinct of{' '}
                  {sel.papers.length * sel.perStudentCount} slots
                </span>
                <span>pool: {sel.pool.subjectRows} rows</span>
                {sel.pool.afterChapterFilter !== sel.pool.subjectRows ? (
                  <span>after chapter filter: {sel.pool.afterChapterFilter}</span>
                ) : null}
                {sel.maxSharedByAnyQuestion >= sel.papers.length ? (
                  <span className="text-amber-700 dark:text-amber-300">
                    sabhi students ko same question mil raha hai
                  </span>
                ) : null}
              </div>

              <ul className="space-y-1.5">
                {sel.papers.map((p) => {
                  const open = openStudent === p.studentId;
                  return (
                    <li key={p.studentId} className="rounded-lg border border-slate-200 dark:border-slate-800">
                      <button
                        type="button"
                        onClick={() => setOpenStudent(open ? null : p.studentId)}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm"
                      >
                        <span className="font-medium tabular-nums">{p.studentId}</span>
                        <span className="text-[11px] text-slate-500">{p.count} questions</span>
                        <span className="ml-auto text-[11px] text-slate-400">{open ? 'hide' : 'show'}</span>
                      </button>
                      {open ? (
                        <ol className="space-y-1.5 border-t border-slate-100 px-3 py-2 dark:border-slate-800">
                          {p.questions.map((q, i) => (
                            <li key={q.id} className="text-[12px] leading-snug">
                              <span className="mr-1 tabular-nums text-slate-400">{i + 1}.</span>
                              <span className="text-slate-700 dark:text-slate-200">{q.short}</span>
                              <span className="ml-1 text-[11px] text-slate-400">
                                {q.chapter ? `${q.chapter} · ` : ''}
                                {q.id} · {q.options} options · {q.marks} marks
                              </span>
                            </li>
                          ))}
                          {p.count === 0 ? <li className="text-[12px] text-rose-700">koi question nahi mila</li> : null}
                        </ol>
                      ) : null}
                    </li>
                  );
                })}
              </ul>

              <h4 className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Most-used questions across these students
              </h4>
              <ul className="grid gap-1 sm:grid-cols-2">
                {sel.byQuestion.slice(0, 12).map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center gap-2 rounded border border-slate-100 px-2 py-1 text-[11px] dark:border-slate-800"
                  >
                    <span className="truncate font-mono text-slate-600 dark:text-slate-300">{e.id}</span>
                    <span className="ml-auto shrink-0 tabular-nums text-slate-500">
                      {e.studentCount}/{sel.papers.length}
                    </span>
                    {e.pinned ? (
                      <span className="shrink-0 rounded bg-violet-100 px-1 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200">
                        all
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
