import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, CircleAlert, CircleX, ExternalLink, FileText, Loader2 } from 'lucide-react';
import { fetchSubmissionReview, saveMentorTestFeedback } from '@/api/tests';
import { apiUrl, AUTH_EVENT, getToken } from '@/api/backendClient';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/utils/format';

const asDrivePreview = (raw) => {
  if (!raw) return '';
  try {
    const url = new URL(raw);
    const host = url.hostname.toLowerCase();
    if (host === 'drive.google.com') {
      const fileMatch = url.pathname.match(/\/file\/d\/([^/]+)/);
      const id = fileMatch?.[1] || url.searchParams.get('id');
      return id ? `https://drive.google.com/file/d/${encodeURIComponent(id)}/preview` : raw;
    }
    if (host === 'docs.google.com') {
      const docMatch = url.pathname.match(/\/document\/d\/([^/]+)/);
      return docMatch?.[1]
        ? `https://docs.google.com/document/d/${encodeURIComponent(docMatch[1])}/preview`
        : raw;
    }
  } catch {
    // A non-absolute URL is left unchanged; internal file routes are fetched below.
  }
  return raw;
};

function DocumentViewer({ label, url, missingMessage }) {
  const [source, setSource] = useState('');
  const [mimeType, setMimeType] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    let objectUrl = '';
    setSource('');
    setMimeType('');
    setError('');

    if (!url) {
      setLoading(false);
      return undefined;
    }

    if (!url.startsWith('/api/student-tests/answer-sheet/')) {
      setSource(asDrivePreview(url));
      setLoading(false);
      return undefined;
    }

    setLoading(true);
    const token = getToken();
    fetch(apiUrl(url), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (response) => {
        if (response.status === 401) {
          window.dispatchEvent(new CustomEvent(AUTH_EVENT));
        }
        if (!response.ok) throw new Error(`Could not load the uploaded file (HTTP ${response.status}).`);
        return { blob: await response.blob(), mime: response.headers.get('content-type') || '' };
      })
      .then(({ blob, mime }) => {
        const created = URL.createObjectURL(blob);
        objectUrl = created;
        if (active) {
          setSource(created);
          setMimeType((mime || blob.type || '').split(';')[0].toLowerCase());
        } else {
          URL.revokeObjectURL(created);
        }
      })
      .catch((reason) => {
        if (active) setError(reason?.message || 'Could not load the uploaded file.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  if (!url) {
    return <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700" role="status">{missingMessage}</div>;
  }
  if (loading) {
    return <div className="flex min-h-48 items-center justify-center gap-2 rounded-lg border border-slate-200 text-sm text-slate-500 dark:border-slate-700"><Loader2 className="h-4 w-4 animate-spin" /> Loading {label.toLowerCase()}…</div>;
  }
  if (error) return <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">{error}</div>;
  if (!source) return null;

  const isImage = mimeType.startsWith('image/') || /\.(?:jpe?g|png|webp)(?:$|[?#])/i.test(url);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>{label}</span>
        <a href={source} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:underline">
          Open full size <ExternalLink className="h-3 w-3" />
        </a>
      </div>
      {isImage ? (
        <img src={source} alt={label} className="mx-auto max-h-[62vh] max-w-full rounded-lg border border-slate-200 object-contain dark:border-slate-700" />
      ) : (
        <iframe title={label} src={source} className="h-[62vh] w-full rounded-lg border border-slate-200 bg-white dark:border-slate-700" />
      )}
      {!url.startsWith('/api/student-tests/answer-sheet/') ? (
        <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline">
          Open original file <ExternalLink className="h-3 w-3" />
        </a>
      ) : null}
    </div>
  );
}

function TextPanel({ title, text, emptyMessage }) {
  return (
    <section className="rounded-lg border border-slate-200 p-4 dark:border-slate-700">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100"><FileText className="h-4 w-4 text-blue-600" />{title}</h3>
      {text ? <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-700 dark:text-slate-300">{text}</pre> : <p className="text-sm text-slate-500">{emptyMessage}</p>}
    </section>
  );
}

function McqReview({ questions = [] }) {
  const correctCount = useMemo(() => questions.filter((question) => question.correct).length, [questions]);
  if (!questions.length) {
    return <div className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700" role="status">Question-by-question answers were not saved for this older submission, so the mistakes cannot be reconstructed.</div>;
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
        {correctCount} of {questions.length} correct · wrong answers are highlighted in red; the answer key is green.
      </div>
      {questions.map((question, questionIndex) => {
        const selected = Number.isInteger(question.selected) ? question.selected : null;
        const answer = Number.isInteger(question.answer) ? question.answer : null;
        const isCorrect = Boolean(question.correct);
        return (
          <article key={question.id || questionIndex} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700" data-testid={`review-question-${questionIndex + 1}`}>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-white">Q{questionIndex + 1}. {question.prompt || question.id || 'Question'}</h3>
                {(question.subject || question.chapter) ? <p className="mt-1 text-xs text-slate-500">{[question.subject, question.chapter].filter(Boolean).join(' · ')}</p> : null}
              </div>
              <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold', isCorrect ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300')}>
                {isCorrect ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleX className="h-3.5 w-3.5" />}
                {isCorrect ? 'Correct' : 'Incorrect'}
              </span>
            </div>
            <div className="space-y-1.5">
              {(question.options || []).map((option, optionIndex) => {
                const isSelected = selected === optionIndex;
                const isAnswer = answer === optionIndex;
                return (
                  <div key={`${question.id || questionIndex}-${optionIndex}`} className={cn('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', isAnswer ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200' : isSelected ? 'border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200' : 'border-slate-100 text-slate-600 dark:border-slate-800 dark:text-slate-400')}>
                    <span className="w-6 shrink-0 font-semibold">{String.fromCharCode(65 + optionIndex)}.</span>
                    <span className="min-w-0 flex-1">{option}</span>
                    {isSelected ? <span className="shrink-0 text-[10px] font-bold uppercase">Student chose</span> : null}
                    {isAnswer ? <span className="shrink-0 text-[10px] font-bold uppercase">Correct answer</span> : null}
                  </div>
                );
              })}
            </div>
            {selected == null ? <p className="mt-2 text-xs font-medium text-amber-700">Student did not select an answer.</p> : null}
            {question.explanation ? <div className="mt-3 rounded-md bg-blue-50/70 px-3 py-2 text-sm text-blue-900 dark:bg-blue-950/30 dark:text-blue-200"><b>Explanation:</b> {question.explanation}</div> : null}
          </article>
        );
      })}
    </div>
  );
}

export default function SubmissionReviewDialog({ open, onOpenChange, student, test }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeMaterial, setActiveMaterial] = useState('student');
  const [mentorRemark, setMentorRemark] = useState('');
  const [savingRemark, setSavingRemark] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState('');
  const [feedbackError, setFeedbackError] = useState('');

  useEffect(() => {
    let active = true;
    setData(null);
    setError('');
    setActiveMaterial('student');
    setMentorRemark('');
    setFeedbackStatus('');
    setFeedbackError('');
    if (!open || !student?.studentId || !test?.testId) {
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    fetchSubmissionReview(student.studentId, test.testId)
      .then((result) => {
        if (active) {
          setData(result);
          setMentorRemark(result?.mentorFeedback?.remark || '');
        }
      })
      .catch((reason) => { if (active) setError(reason?.message || 'Could not load submission review.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, student?.studentId, test?.testId]);

  const kind = data?.test?.kind || test?.kind;
  const paperTabs = [
    ['student', 'Student answer'],
    ['paper', 'Question paper'],
    ['key', 'Answer key'],
    ['scheme', 'Marking scheme'],
  ];
  const summary = data?.submission;

  const saveRemark = async () => {
    if (savingRemark || !student?.studentId || !test?.testId) return;
    setSavingRemark(true);
    setFeedbackStatus('');
    setFeedbackError('');
    try {
      const saved = await saveMentorTestFeedback(student.studentId, test.testId, mentorRemark);
      const remark = saved?.remark || '';
      setMentorRemark(remark);
      setData((current) => current ? {
        ...current,
        mentorFeedback: { ...(current.mentorFeedback || {}), remark, updatedAt: saved?.updatedAt || '' },
      } : current);
      setFeedbackStatus(remark ? 'Saved. The student will see this on their test.' : 'Remark removed.');
    } catch (reason) {
      setFeedbackError(reason?.message || 'Could not save the mentor remark.');
    } finally {
      setSavingRemark(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100vw-1rem)] max-w-5xl max-h-[92vh] overflow-y-auto">
        <DialogHeader className="pr-8">
          <DialogTitle>Submission review</DialogTitle>
          <DialogDescription>
            {student?.studentName || student?.studentId || 'Student'} · {test?.title || 'Test'}
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div role="status" className="flex min-h-48 items-center justify-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading answers and reference sheets…</div>
        ) : error ? (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>
        ) : data ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/70">
              <span className="font-semibold text-slate-900 dark:text-white">{data.student?.studentName || student?.studentName || student?.studentId}</span>
              <span className="text-xs text-slate-500">{data.student?.studentId || student?.studentId}</span>
              <span className="ml-auto rounded-full bg-white px-3 py-1 text-sm font-bold text-slate-800 shadow-sm dark:bg-slate-900 dark:text-slate-100">
                Marks: {summary?.score ?? '—'}{summary?.total ? ` / ${summary.total}` : ''}{summary?.scorePct != null ? ` · ${summary.scorePct}%` : ''}
              </span>
              {summary?.selfMarks ? <span className="text-xs text-violet-700 dark:text-violet-300">Student self-evaluated</span> : null}
            </div>

            {kind === 'paper-test' ? (
              <>
                <div className="flex flex-wrap gap-2 border-b border-slate-200 pb-2 dark:border-slate-700" role="tablist" aria-label="Submission materials">
                  {paperTabs.map(([key, label]) => (
                    <button key={key} type="button" role="tab" aria-selected={activeMaterial === key} onClick={() => setActiveMaterial(key)} className={cn('rounded-full px-3 py-1.5 text-xs font-semibold', activeMaterial === key ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300')}>
                      {label}
                    </button>
                  ))}
                </div>
                {activeMaterial === 'student' ? (
                  <div className="space-y-3">
                    <DocumentViewer label={`Student's uploaded answer sheet${data.answerFileName ? ` · ${data.answerFileName}` : ''}`} url={summary?.answerUrl} missingMessage="No student answer file was attached to this submission. If the student only sent marks, the written work was not saved and cannot be recreated." />
                    {summary?.remarks ? <TextPanel title="Student's note" text={summary.remarks} emptyMessage="No note." /> : null}
                  </div>
                ) : null}
                {activeMaterial === 'paper' ? <DocumentViewer label="Question paper" url={data.test?.questionPaperUrl} missingMessage="No question paper is attached to this test record." /> : null}
                {activeMaterial === 'key' ? (
                  <div className="grid gap-4 lg:grid-cols-2">
                    <DocumentViewer label="Uploaded answer sheet / key" url={data.test?.answerSheetUrl} missingMessage="No answer-sheet file is attached." />
                    <TextPanel title="Typed answer key" text={data.test?.answerSheetText} emptyMessage="No typed answer key was saved for this test." />
                  </div>
                ) : null}
                {activeMaterial === 'scheme' ? <TextPanel title="Marking scheme" text={data.test?.markingScheme} emptyMessage="No marking scheme was saved for this test." /> : null}
                {data.test?.instructions ? <p className="text-xs text-slate-500">Test instructions: {data.test.instructions}</p> : null}
              </>
            ) : (
              <>
                {data.reviewAvailable ? <McqReview questions={data.mcqReview} /> : (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">This submission has marks but no saved question-by-question review. The app cannot reconstruct answers that were not recorded.</div>
                )}
              </>
            )}
            <section className="rounded-xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900/70 dark:bg-blue-950/20" aria-label="Mentor remark">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Message for this student</h3>
                  <p className="mt-0.5 text-xs text-slate-500">Shown on this test in the student app. Separate from their self-evaluation note; marks are not changed.</p>
                </div>
                <span className="shrink-0 text-[11px] text-slate-400">{mentorRemark.length}/2000</span>
              </div>
              <textarea
                data-testid="mentor-test-remark"
                value={mentorRemark}
                onChange={(event) => { setMentorRemark(event.target.value); setFeedbackStatus(''); setFeedbackError(''); }}
                maxLength={2000}
                rows={3}
                placeholder="Write your opinion or guidance about this test…"
                className="w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <div className="min-h-5 text-xs">
                  {feedbackError ? <span role="alert" className="text-rose-700 dark:text-rose-300">{feedbackError}</span>
                    : feedbackStatus ? <span role="status" className="text-emerald-700 dark:text-emerald-300">{feedbackStatus}</span>
                      : <span className="text-slate-500">Only this student can see the saved remark.</span>}
                </div>
                <button
                  type="button"
                  data-testid="save-mentor-test-remark"
                  onClick={saveRemark}
                  disabled={savingRemark || (!mentorRemark.trim() && !data.mentorFeedback?.remark)}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {savingRemark ? 'Saving…' : mentorRemark.trim() ? 'Save remark' : data.mentorFeedback?.remark ? 'Remove remark' : 'Save remark'}
                </button>
              </div>
            </section>
            {summary?.at ? <p className="text-right text-[11px] text-slate-400">Submitted: {new Date(summary.at).toLocaleString('en-IN')}</p> : null}
          </div>
        ) : (
          <div role="status" className="py-8 text-center text-sm text-slate-500">Choose a submitted student to review their work.</div>
        )}
      </DialogContent>
    </Dialog>
  );
}
