// Mentor test authoring — create a test, attach the question paper / answer
// sheet, publish it to a batch+group, edit or delete it later.
//
// Layout: one card per created test (newest first) + a form card that opens for
// "Create test" or "Edit". English-only UI. Files upload straight from the
// browser (PDF/JPG/PNG up to 10 MB) and land in the mentor's own Drive folders.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  ExternalLink,
  FileText,
  Loader2,
  Paperclip,
  Pencil,
  Plus,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import { normalizeStudentGroup } from '@/utils/studentGroup';
import { ALL_BATCHES, ENROLLMENT_BATCHES } from '@/constants/batches';
import { cn } from '@/utils/format';
import {
  createMentorTest,
  deleteMentorTest,
  formatBytes,
  listMentorTests,
  setMentorTestPublished,
  updateMentorTest,
  uploadTestFile,
} from '@/api/mentorTestsAdmin';

const SUBJECT_GROUP_MAP = {
  Costing: 'Group 2',
  Audit: 'Group 2',
  FM: 'Group 2',
  SM: 'Group 2',
  Accounts: 'Group 1',
  Law: 'Group 1',
  DT: 'Group 1',
  GST: 'Group 1',
};

const SUBJECTS = Object.keys(SUBJECT_GROUP_MAP);
const GROUP_OPTIONS = ['Both Groups', 'Group 1', 'Group 2'];
const BATCH_OPTIONS = [ALL_BATCHES, ...ENROLLMENT_BATCHES];
const KINDS = [
  { key: 'paper-test', label: 'Paper test', hint: 'Student solves the paper, then self-checks with the answer sheet.' },
  { key: 'mcq-test', label: 'MCQ test', hint: 'Questions come from the question bank; answers are auto-checked.' },
];

const emptyForm = () => ({
  testId: '',
  title: '',
  kind: 'paper-test',
  subject: SUBJECTS[0],
  batch: BATCH_OPTIONS[0],
  group: GROUP_OPTIONS[0],
  test_date: '',
  window_start: '',
  window_end: '',
  duration_minutes: '',
  total_marks: '',
  question_count: '',
  instructions: '',
  paper_url: '',
  answer_sheet_url: '',
  answer_sheet_text: '',
  marking_scheme: '',
  published: false,
});

const fmtDay = (iso) => {
  if (!iso) return '';
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
};

const fmtWhen = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

// ── small building blocks ───────────────────────────────────────────────────
function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint ? <span className="mt-1 block text-[11px] text-slate-400">{hint}</span> : null}
    </label>
  );
}

const inputCls =
  'w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40';

function AttachRow({ label, kind, url, fileName, busy, error, onPick, onClear, testId }) {
  const inputRef = useRef(null);
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-900/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</span>
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs font-semibold text-[#2563EB] hover:underline"
          >
            Open <ExternalLink className="w-3 h-3" />
          </a>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          className="hidden"
          data-testid={`upload-input-${kind}`}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) onPick(file);
          }}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          data-testid={`upload-${kind}${testId ? `-${testId}` : ''}`}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:border-[#2563EB] disabled:opacity-60"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Paperclip className="w-3.5 h-3.5" />}
          {busy ? 'Uploading…' : url ? 'Replace file' : 'Upload file'}
        </button>
        {url ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="w-3.5 h-3.5" />
            {fileName || 'Attached'}
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">PDF, JPG or PNG · up to 10 MB</span>
        )}
        {url ? (
          <button
            type="button"
            onClick={onClear}
            className="text-[11px] font-semibold text-slate-400 hover:text-rose-600"
          >
            Remove
          </button>
        ) : null}
      </div>
      {error ? <p className="mt-2 text-[11px] font-semibold text-rose-600">{error}</p> : null}
    </div>
  );
}

function StatusChip({ published }) {
  return published ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 dark:bg-emerald-500/10 px-2.5 py-1 text-[11px] font-bold text-emerald-700 dark:text-emerald-300">
      Live for students
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 dark:bg-slate-800 px-2.5 py-1 text-[11px] font-bold text-slate-600 dark:text-slate-300">
      Draft
    </span>
  );
}

// ── the authoring card ──────────────────────────────────────────────────────
export default function TestAuthoring({ scopedBatch, scopedGroup } = {}) {
  const [tests, setTests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [formError, setFormError] = useState('');
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [confirmId, setConfirmId] = useState(''); // inline confirm: 'publish:<id>' | 'delete:<id>'
  const [form, setForm] = useState({ ...emptyForm(), ...(scopedBatch ? { batch: scopedBatch, group: scopedGroup } : {}) });
  const [uploads, setUploads] = useState({ qp: null, as: null });
  const [uploadBusy, setUploadBusy] = useState('');
  const [uploadError, setUploadError] = useState({ qp: '', as: '' });

  const editing = Boolean(form.testId);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await listMentorTests();
      setTests((data?.items || []).filter(t => !scopedBatch || (t.batch === scopedBatch && normalizeStudentGroup(t.group) === normalizeStudentGroup(scopedGroup))));
    } catch (e) {
      setLoadError(e?.message || 'Could not load your tests.');
    } finally {
      setLoading(false);
    }
  }, [scopedBatch, scopedGroup]);

  useEffect(() => { load(); }, [load]);

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));

  const startCreate = () => {
    setForm({ ...emptyForm(), ...(scopedBatch ? { batch: scopedBatch, group: scopedGroup } : {}) });
    setUploads({ qp: null, as: null });
    setUploadError({ qp: '', as: '' });
    setFormError('');
    setNotice('');
    setOpen(true);
  };

  const startEdit = (test) => {
    setForm({
      testId: test.testId,
      exclusiveGroup: !!test.exclusiveGroup,
      title: test.title || '',
      kind: test.kind || 'paper-test',
      subject: test.subject || SUBJECTS[0],
      batch: test.batch || ALL_BATCHES,
      group: test.group || 'Both Groups',
      test_date: test.test_date || '',
      window_start: test.window_start || '',
      window_end: test.window_end || '',
      duration_minutes: test.duration_minutes ?? '',
      total_marks: test.total_marks ?? '',
      question_count: test.question_count ?? '',
      instructions: test.instructions || '',
      paper_url: test.paper_url || '',
      answer_sheet_url: test.answer_sheet_url || '',
      answer_sheet_text: test.answer_sheet_text || '',
      marking_scheme: test.marking_scheme || '',
      published: !!test.published,
    });
    setUploads({ qp: null, as: null });
    setUploadError({ qp: '', as: '' });
    setFormError('');
    setNotice('');
    setOpen(true);
  };

  const pickFile = async (kind, file) => {
    setUploadBusy(kind);
    setUploadError((u) => ({ ...u, [kind]: '' }));
    setFormError('');
    try {
      const res = await uploadTestFile({ kind: kind === 'qp' ? 'qp' : 'as', file });
      setUploads((u) => ({ ...u, [kind]: res }));
      set(kind === 'qp' ? 'paper_url' : 'answer_sheet_url', res.downloadUrl || res.viewUrl);
      setNotice(`${kind === 'qp' ? 'Question paper' : 'Answer sheet'} uploaded (${formatBytes(res.bytes)}).`);
    } catch (e) {
      setUploadError((u) => ({ ...u, [kind]: e?.message || 'Upload failed.' }));
    } finally {
      setUploadBusy('');
    }
  };

  const submit = async () => {
    if (!form.title.trim()) { setFormError('Test ka naam likhein.'); return; }
    setSaving(true);
    setFormError('');
    setNotice('');
    try {
      const payload = {
        title: form.title.trim(),
        kind: form.kind,
        subject: form.subject,
        batch: scopedBatch || form.batch,
        exclusiveGroup: editing ? !!form.exclusiveGroup : !!scopedGroup,
        group: scopedGroup || form.group,
        test_date: form.test_date || null,
        window_start: form.window_start || null,
        window_end: form.window_end || null,
        duration_minutes: form.duration_minutes === '' ? null : Number(form.duration_minutes),
        total_marks: form.total_marks === '' ? null : Number(form.total_marks),
        question_count: form.kind === 'mcq-test' && form.question_count !== '' ? Number(form.question_count) : null,
        instructions: form.instructions || null,
        paper_url: form.paper_url || null,
        answer_sheet_url: form.answer_sheet_url || null,
        answer_sheet_text: form.answer_sheet_text || null,
        marking_scheme: form.marking_scheme || null,
      };
      if (editing) {
        await updateMentorTest(form.testId, payload);
        setNotice('Test updated.');
      } else {
        const res = await createMentorTest(payload);
        setNotice(`"${res?.test?.title || payload.title}" saved as a draft. Publish it when you are ready.`);
      }
      setOpen(false);
      setForm({ ...emptyForm(), ...(scopedBatch ? { batch: scopedBatch, group: scopedGroup } : {}) });
      await load();
    } catch (e) {
      setFormError(e?.message || 'Could not save the test.');
    } finally {
      setSaving(false);
    }
  };

  const togglePublish = async (test) => {
    setBusyId(test.testId);
    setNotice('');
    try {
      await setMentorTestPublished(test.testId, !test.published);
      setNotice(
        test.published
          ? `"${test.title}" is back to draft — students no longer see it.`
          : `"${test.title}" is live. Students in the selected batch/group got a notification.`,
      );
      setConfirmId('');
      await load();
    } catch (e) {
      setLoadError(e?.message || 'Could not change the publish state.');
    } finally {
      setBusyId('');
    }
  };

  const remove = async (test) => {
    setBusyId(test.testId);
    setNotice('');
    try {
      await deleteMentorTest(test.testId);
      setNotice(`"${test.title}" deleted.`);
      setConfirmId('');
      await load();
    } catch (e) {
      setLoadError(e?.message || 'Could not delete the test.');
    } finally {
      setBusyId('');
    }
  };

  const stats = useMemo(() => ({
    total: tests.length,
    live: tests.filter((t) => t.published).length,
    papers: tests.filter((t) => (t.kind || 'mcq-test') === 'paper-test').length,
  }), [tests]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm text-slate-500 dark:text-slate-400">
          <span className="font-semibold text-slate-700 dark:text-slate-200">{stats.total}</span> tests ·{' '}
          <span className="font-semibold text-emerald-600">{stats.live}</span> live ·{' '}
          <span className="font-semibold text-slate-700 dark:text-slate-200">{stats.papers}</span> paper tests
        </div>
        <button
          type="button"
          onClick={startCreate}
          data-testid="create-test"
          className="ml-auto inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white hover:bg-[#1d4ed8]"
        >
          <Plus className="w-4 h-4" /> Create test
        </button>
      </div>

      {notice ? (
        <div className="rounded-lg border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/70 dark:bg-emerald-500/5 px-4 py-3 text-sm text-emerald-800 dark:text-emerald-300">
          {notice}
        </div>
      ) : null}
      {loadError ? (
        <div className="rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/70 dark:bg-rose-500/5 px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
          {loadError}
        </div>
      ) : null}

      {/* Form */}
      {open ? (
        <div
          className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 sm:p-5 space-y-4"
          data-testid="test-form"
        >
          <div className="flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-[#2563EB]" />
            <h2 className="text-sm font-bold text-slate-800 dark:text-slate-100">
              {editing ? `Edit test · ${form.testId}` : 'New test'}
            </h2>
            <button
              type="button"
              onClick={() => { setOpen(false); setForm({ ...emptyForm(), ...(scopedBatch ? { batch: scopedBatch, group: scopedGroup } : {}) }); setFormError(''); }}
              className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
            >
              <X className="w-3.5 h-3.5" /> Close
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="sm:col-span-2 lg:col-span-3">
              <Field label="Test name">
                <input
                  className={inputCls}
                  value={form.title}
                  onChange={(e) => set('title', e.target.value)}
                  placeholder="e.g. Audit Chapter 3 — Practice Test"
                  data-testid="test-title"
                />
              </Field>
            </div>

            <div className="sm:col-span-2 lg:col-span-3">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Type</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {KINDS.map((k) => (
                  <button
                    key={k.key}
                    type="button"
                    onClick={() => set('kind', k.key)}
                    className={cn(
                      'rounded-lg border px-3 py-2 text-xs font-semibold text-left transition-colors',
                      form.kind === k.key
                        ? 'border-[#2563EB] bg-[#2563EB]/5 text-[#2563EB]'
                        : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:border-[#2563EB]',
                    )}
                  >
                    <span className="block">{k.label}</span>
                    <span className="mt-0.5 block text-[10px] font-normal text-slate-400">{k.hint}</span>
                  </button>
                ))}
              </div>
            </div>

            <Field label="Subject">
              <select
                className={inputCls}
                value={form.subject}
                onChange={(e) => {
                  const subject = e.target.value;
                  set('subject', subject);
                  if (!scopedGroup) set('group', SUBJECT_GROUP_MAP[subject] || 'Both Groups');
                }}
                data-testid="test-subject"
              >
                {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>

            <Field label="Batch">
              <select className={inputCls} disabled={!!scopedBatch} value={form.batch} onChange={(e) => set('batch', e.target.value)} data-testid="test-batch">
                {BATCH_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </Field>

            <Field label="Group">
              <select className={inputCls} disabled={!!scopedGroup} value={form.group} onChange={(e) => set('group', e.target.value)} data-testid="test-group">
                {GROUP_OPTIONS.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            </Field>

            <Field label="Test date">
              <input type="date" className={inputCls} value={form.test_date} onChange={(e) => set('test_date', e.target.value)} />
            </Field>

            <Field label="Window opens" hint="Students can attempt from this time.">
              <input type="datetime-local" className={inputCls} value={form.window_start} onChange={(e) => set('window_start', e.target.value)} />
            </Field>

            <Field label="Window closes" hint="Leave both blank for an always-open test.">
              <input type="datetime-local" className={inputCls} value={form.window_end} onChange={(e) => set('window_end', e.target.value)} />
            </Field>

            <Field label="Duration (minutes)">
              <input type="number" min="1" max="600" className={inputCls} value={form.duration_minutes} onChange={(e) => set('duration_minutes', e.target.value)} />
            </Field>

            <Field label="Total marks">
              <input type="number" min="1" max="1000" className={inputCls} value={form.total_marks} onChange={(e) => set('total_marks', e.target.value)} />
            </Field>

            {form.kind === 'mcq-test' ? (
              <Field label="Questions" hint="How many questions to pick from the bank.">
                <input type="number" min="1" max="500" className={inputCls} value={form.question_count} onChange={(e) => set('question_count', e.target.value)} />
              </Field>
            ) : (
              <Field label="Questions on paper" hint="Printed on the question paper.">
                <input type="number" min="1" max="500" className={inputCls} value={form.question_count} onChange={(e) => set('question_count', e.target.value)} />
              </Field>
            )}

            <div className="sm:col-span-2 lg:col-span-3">
              <Field label="Instructions for students" hint="Shown at the top of the test in the app.">
                <textarea
                  rows={2}
                  className={inputCls}
                  value={form.instructions}
                  onChange={(e) => set('instructions', e.target.value)}
                  placeholder="e.g. Attempt all questions. Write answers in the answer sheet and upload photos."
                />
              </Field>
            </div>
          </div>

          {form.kind === 'paper-test' ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <AttachRow
                label="Question paper"
                kind="qp"
                url={form.paper_url}
                fileName={uploads.qp?.fileName}
                busy={uploadBusy === 'qp'}
                error={uploadError.qp}
                onPick={(file) => pickFile('qp', file)}
                onClear={() => { set('paper_url', ''); setUploads((u) => ({ ...u, qp: null })); }}
                testId={form.testId}
              />
              <AttachRow
                label="Answer sheet"
                kind="as"
                url={form.answer_sheet_url}
                fileName={uploads.as?.fileName}
                busy={uploadBusy === 'as'}
                error={uploadError.as}
                onPick={(file) => pickFile('as', file)}
                onClear={() => { set('answer_sheet_url', ''); setUploads((u) => ({ ...u, as: null })); }}
                testId={form.testId}
              />
              <div className="lg:col-span-2 grid gap-3 sm:grid-cols-2">
                <Field label="Answer key text (optional)" hint="Type the answers if you do not want to upload a sheet.">
                  <textarea rows={3} className={inputCls} value={form.answer_sheet_text} onChange={(e) => set('answer_sheet_text', e.target.value)} />
                </Field>
                <Field label="Marking scheme (optional)" hint="How marks are awarded — students read this while self-checking.">
                  <textarea rows={3} className={inputCls} value={form.marking_scheme} onChange={(e) => set('marking_scheme', e.target.value)} />
                </Field>
              </div>
            </div>
          ) : null}

          {formError ? (
            <div className="rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/70 dark:bg-rose-500/5 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
              {formError}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              data-testid="save-test"
              className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white hover:bg-[#1d4ed8] disabled:opacity-60"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {editing ? 'Save changes' : 'Save as draft'}
            </button>
            <span className="text-xs text-slate-400">
              Saved tests stay hidden until you press <strong className="font-semibold">Publish</strong>. Publish karte hi students ko app notification jaati hai.
            </span>
          </div>
        </div>
      ) : null}

      {/* Created tests */}
      <div className="space-y-3">
        {loading ? (
          <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-10 text-center text-sm text-slate-500">
            Loading your tests…
          </div>
        ) : tests.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 dark:border-slate-700 px-4 py-10 text-center">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">No tests created yet</p>
            <p className="mt-1 text-xs text-slate-500">
              Press <strong className="font-semibold">Create test</strong>, upload the question paper, then publish it to a batch. Students get a notification and can open it in the Tests tab.
            </p>
          </div>
        ) : tests.map((t) => (
          <div
            key={t.testId}
            data-testid={`test-${t.testId}`}
            className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100">{t.title}</h3>
              <span className="rounded-full bg-blue-50 dark:bg-blue-500/10 px-2 py-0.5 text-[11px] font-bold text-blue-700 dark:text-blue-300">
                {(t.kind || 'mcq-test') === 'paper-test' ? 'Paper' : 'MCQ'}
              </span>
              <StatusChip published={t.published} />
              <span className="ml-auto text-[11px] text-slate-400">{t.testId}</span>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
              {t.subject ? <span>{t.subject}</span> : null}
              <span>{t.batch || ALL_BATCHES}</span>
              <span>{t.group || 'Both Groups'}</span>
              {t.test_date ? (
                <span className="inline-flex items-center gap-1"><CalendarDays className="w-3.5 h-3.5" />{fmtDay(t.test_date)}</span>
              ) : null}
              {t.window_start || t.window_end ? (
                <span>{fmtWhen(t.window_start) || 'now'} → {fmtWhen(t.window_end) || 'open'}</span>
              ) : null}
              {t.total_marks ? <span>{t.total_marks} marks</span> : null}
              {t.duration_minutes ? <span>{t.duration_minutes} min</span> : null}
              {t.question_count ? <span>{t.question_count} questions</span> : null}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {t.paper_url ? (
                <a href={t.paper_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:border-[#2563EB]">
                  <FileText className="w-3.5 h-3.5" /> Question paper
                </a>
              ) : (t.kind || '') === 'paper-test' ? (
                <span className="inline-flex items-center gap-1 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-500/5 px-2.5 py-1.5 text-xs font-semibold text-amber-700 dark:text-amber-300">
                  <Paperclip className="w-3.5 h-3.5" /> No question paper yet
                </span>
              ) : null}

              {t.answer_sheet_url ? (
                <a href={t.answer_sheet_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:border-[#2563EB]">
                  <FileText className="w-3.5 h-3.5" /> Answer sheet
                </a>
              ) : null}

              <div className="ml-auto flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => startEdit(t)}
                  data-testid={`edit-test-${t.testId}`}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:border-[#2563EB]"
                >
                  <Pencil className="w-3.5 h-3.5" /> Edit
                </button>

                {confirmId === `publish:${t.testId}` ? (
                  <button
                    type="button"
                    onClick={() => togglePublish(t)}
                    disabled={busyId === t.testId}
                    data-testid={`confirm-publish-${t.testId}`}
                    className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-bold text-white hover:bg-emerald-700 disabled:opacity-60"
                  >
                    {busyId === t.testId ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                    {t.published ? 'Confirm: back to draft' : 'Confirm publish — sends notification'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmId(`publish:${t.testId}`)}
                    data-testid={`publish-test-${t.testId}`}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-bold text-white',
                      t.published ? 'bg-amber-500 hover:bg-amber-600' : 'bg-emerald-600 hover:bg-emerald-700',
                    )}
                  >
                    <Send className="w-3.5 h-3.5" /> {t.published ? 'Unpublish' : 'Publish'}
                  </button>
                )}

                {confirmId === `delete:${t.testId}` ? (
                  <button
                    type="button"
                    onClick={() => remove(t)}
                    disabled={busyId === t.testId}
                    data-testid={`confirm-delete-${t.testId}`}
                    className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-2.5 py-1.5 text-xs font-bold text-white hover:bg-rose-700 disabled:opacity-60"
                  >
                    {busyId === t.testId ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />} Confirm delete
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirmId(`delete:${t.testId}`)}
                    data-testid={`delete-test-${t.testId}`}
                    className="inline-flex items-center gap-1 rounded-lg border border-rose-200 dark:border-rose-900/60 px-2.5 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-500/10"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                )}
              </div>
            </div>

            {confirmId === `publish:${t.testId}` && !t.published ? (
              <p className="mt-2 text-[11px] text-slate-500">
                Publishing makes the test visible to {t.batch || ALL_BATCHES} · {t.group || 'Both Groups'} and sends them a push notification.
              </p>
            ) : null}
            {confirmId === `delete:${t.testId}` ? (
              <p className="mt-2 text-[11px] text-rose-600">
                This removes the test from the app. Already-submitted answers stay in the records.
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
