import { useEffect, useMemo, useState } from 'react';
import { Trash2, Upload } from 'lucide-react';
import { fetchTargetOptions, fetchTargets, previewTargetAudience, publishTarget, removeTarget } from '@/api/dailyTargets';

const ALL = 'All';

const todayIst = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

function linesToTasks(text) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 12)
    .map((label) => ({ label }));
}

export default function DailyTargets() {
  const [options, setOptions] = useState({ attempts: [], groups: [], batches: [], subjects: [] });
  const [targets, setTargets] = useState([]);
  const [startDate, setStartDate] = useState(todayIst());
  const [endDate, setEndDate] = useState('');
  const [attempt, setAttempt] = useState(ALL);
  const [group, setGroup] = useState(ALL);
  const [batch, setBatch] = useState(ALL);
  const [subject, setSubject] = useState(ALL);
  const [customSubject, setCustomSubject] = useState('');
  const [taskText, setTaskText] = useState('');
  const [audience, setAudience] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = () => {
    fetchTargetOptions().then(setOptions).catch((err) => setError(err.message || 'Could not load student groups.'));
    fetchTargets().then((res) => setTargets(res?.targets || [])).catch((err) => setError(err.message || 'Could not load targets.'));
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    let alive = true;
    previewTargetAudience({ attempt, group, batch })
      .then((res) => { if (alive) setAudience(res); })
      .catch(() => { if (alive) setAudience(null); });
    return () => { alive = false; };
  }, [attempt, group, batch]);

  const subjectChoices = useMemo(() => [ALL, ...(options.subjects || []), 'Other'], [options.subjects]);
  const paper = subject === 'Other' ? customSubject.trim() : subject;

  const publish = async (event) => {
    event.preventDefault();
    const tasks = linesToTasks(taskText);
    if (!tasks.length) {
      setError('Write at least one task, one line each.');
      return;
    }
    if (subject === 'Other' && !paper) {
      setError('Type the subject name.');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await publishTarget({
        startDate,
        endDate: endDate || startDate,
        attempt,
        group,
        batch,
        subject: paper || ALL,
        tasks,
      });
      const reminder = res?.target?.revisionReminder || '';
      const source = res?.target?.reminderSource === 'groq' ? 'Groq wrote the revision reminder.' : 'Groq was busy, so a plain revision reminder was saved.';
      setNotice(`${source} ${reminder}`);
      setTaskText('');
      load();
    } catch (err) {
      setError(err.message || 'Could not publish the target.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    setError('');
    try {
      await removeTarget(id);
      setTargets((prev) => prev.filter((row) => row.id !== id));
    } catch (err) {
      setError(err.message || 'Could not remove that target.');
    }
  };

  return (
    <div className="space-y-6" data-testid="daily-targets-page">
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-3xl">
        You write the study target. Students in the selected attempt, group, and batch see that list.
        Groq does not create the target. It only writes a revision reminder from the lines you enter.
      </p>

      <form onSubmit={publish} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Date">
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required className={inputClass} />
          </Field>
          <Field label="Repeat until (optional)">
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className={inputClass} />
          </Field>
          <Field label="Attempt">
            <Select value={attempt} onChange={setAttempt} options={[ALL, ...options.attempts]} />
          </Field>
          <Field label="Group">
            <Select value={group} onChange={setGroup} options={[ALL, ...options.groups]} />
          </Field>
          <Field label="Batch">
            <Select value={batch} onChange={setBatch} options={[ALL, ...options.batches]} />
          </Field>
          <Field label="Subject">
            <Select value={subject} onChange={setSubject} options={subjectChoices} />
          </Field>
        </div>
        {subject === 'Other' && (
          <input
            value={customSubject}
            onChange={(e) => setCustomSubject(e.target.value)}
            placeholder="Subject name"
            className={inputClass}
          />
        )}
        <Field label="Tasks, one per line">
          <textarea
            value={taskText}
            onChange={(e) => setTaskText(e.target.value)}
            rows={6}
            placeholder={'AS 10 — read the recognition criteria\nSolve two questions from the module'}
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200"
          />
        </Field>
        <p className="text-sm text-slate-600 dark:text-slate-300" data-testid="target-audience-count">
          {audience ? `This will show for ${audience.count} student${audience.count === 1 ? '' : 's'}.` : 'Checking who will see this...'}
          {audience?.names?.length ? ` Includes ${audience.names.join(', ')}.` : ''}
        </p>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {notice && <p className="text-sm text-emerald-700 dark:text-emerald-400">{notice}</p>}
        <button
          type="submit"
          disabled={busy}
          className="h-11 px-4 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center gap-2 disabled:opacity-60"
        >
          <Upload className="w-4 h-4" /> {busy ? 'Publishing...' : 'Publish target'}
        </button>
      </form>

      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Published</h2>
        {targets.length === 0 && <p className="text-sm text-slate-500">No target is published yet. Until you publish one, the phone keeps its own short list.</p>}
        {targets.map((row) => (
          <article key={row.id} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-semibold text-slate-900 dark:text-white">
                  {row.subject} · {row.startDate}{row.endDate && row.endDate !== row.startDate ? ` to ${row.endDate}` : ''}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  Attempt {row.attempt} · Group {row.group} · Batch {row.batch} · {row.studentCount} students
                </div>
              </div>
              <button type="button" onClick={() => remove(row.id)} className="text-slate-400 hover:text-red-600" aria-label="Remove target">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <ul className="mt-3 space-y-1 text-sm text-slate-700 dark:text-slate-200">
              {(row.tasks || []).map((task) => <li key={task.id}>{task.label}</li>)}
            </ul>
            {row.revisionReminder && (
              <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                <span className="font-semibold">Revision reminder{row.reminderSource === 'groq' ? ' by Groq' : ''}: </span>
                {row.revisionReminder}
              </p>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

const inputClass = 'w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200 outline-none focus:border-[#2563EB]';

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="block text-xs font-semibold text-slate-500 mb-1.5">{label}</span>
      {children}
    </label>
  );
}

function Select({ value, onChange, options }) {
  const unique = [...new Set(options.filter(Boolean))];
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
      {unique.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
  );
}
