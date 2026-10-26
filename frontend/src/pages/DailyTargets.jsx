import { useEffect, useMemo, useState } from 'react';
import { Trash2, Upload } from 'lucide-react';
import { backfillTargetReminders, fetchTargetOptions, fetchTargets, previewTargetAudience, publishTarget, removeTarget, regenerateTargetReminder } from '@/api/dailyTargets';

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
  const [generatingId, setGeneratingId] = useState('');
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMsg, setBackfillMsg] = useState('');

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
      if (res?.target?.reminderSource !== 'groq' || !reminder.trim()) {
        // The target IS published - only the AI reminder is missing. Telling the
        // mentor "it failed" made some of them publish a second, duplicate target.
        setNotice('Target published. The AI reminder could not be generated just now, so it is pending - use "Generate AI reminder" on that target to retry.');
        setTaskText('');
        load();
        return;
      }
      setNotice(`Published with an AI-generated revision reminder. ${reminder}`);
      setTaskText('');
      load();
    } catch (err) {
      setError(err.message || 'Could not publish the target.');
    } finally {
      setBusy(false);
    }
  };

  const generateReminder = async (id) => {
    if (generatingId) return;
    setGeneratingId(id);
    setError('');
    setNotice('');
    try {
      const res = await regenerateTargetReminder(id);
      if (res?.target?.reminderSource !== 'groq' || !res?.target?.revisionReminder?.trim()) {
        throw new Error('The server did not confirm an AI reminder. Please refresh the published list.');
      }
      setTargets((prev) => prev.map((row) => row.id === id ? res.target : row));
      setNotice('AI-generated reminder saved on the existing target. No duplicate target was published.');
    } catch (err) {
      setError(err.message || 'Could not generate the AI reminder. The existing target was not changed.');
    } finally {
      setGeneratingId('');
    }
  };

  // A target whose date has passed is never opened again by a student, so a
  // missing AI reminder on it is noise, not a problem worth an amber warning.
  const today = todayIst();
  const isCurrent = (row) => !row.endDate || row.endDate >= today;
  const pendingReminders = useMemo(
    () => targets.filter((row) => row.reminderSource !== 'groq' && isCurrent(row)),
    [targets], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const generateAllReminders = async () => {
    if (backfilling) return;
    setBackfilling(true);
    setError('');
    setNotice('');
    let generated = 0;
    let failed = 0;
    let stillMissing = pendingReminders.length;
    let guard = 0;
    try {
      do {
        const res = await backfillTargetReminders({ limit: 5 });
        generated += res?.generated || 0;
        failed += (res?.failed || []).length;
        stillMissing = res?.stillMissing || 0;
        setBackfillMsg(`Generating… ${generated} added${stillMissing ? `, ${stillMissing} to go` : ''}`);
        guard += 1;
      } while (stillMissing > 0 && generated > 0 && guard < 20);
      const parts = [`${generated} AI reminder${generated === 1 ? '' : 's'} added to the published targets.`];
      if (failed) parts.push(`${failed} could not be generated - run it once more in a minute.`);
      if (!generated && !failed) parts.push('Nothing was pending.');
      setNotice(parts.join(' '));
      load();
    } catch (err) {
      setError(err.message || 'Could not generate the AI reminders. No target was changed.');
    } finally {
      setBackfilling(false);
      setBackfillMsg('');
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
        Groq does not create the target. The student does it on the timer, then answers the receipt questions.
        Those marks decide weak, average, or strong. Weak comes back in 1 day, average in 3 days, strong in 7 days, and above 85% in 14 days.
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
          <Upload className="w-4 h-4" /> {busy ? 'Generating AI reminder...' : 'Publish target'}
        </button>
      </form>

      {pendingReminders.length > 0 && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-500/40 dark:bg-amber-500/10" data-testid="reminder-backfill-banner">
          <p className="text-sm text-amber-800 dark:text-amber-300">
            {pendingReminders.length} published target{pendingReminders.length === 1 ? '' : 's'} still need an AI revision reminder.
          </p>
          <button
            type="button"
            onClick={generateAllReminders}
            disabled={backfilling}
            className="mt-2 px-3 py-2 rounded-lg border border-amber-400 bg-white text-sm font-semibold text-amber-800 disabled:opacity-60 dark:bg-slate-900 dark:text-amber-300"
          >
            {backfilling ? (backfillMsg || 'Generating…') : 'Generate all missing AI reminders'}
          </button>
        </div>
      )}

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
            {row.reminderSource === 'groq' && row.revisionReminder ? (
              <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                <span className="font-semibold">AI revision reminder by Groq: </span>
                {row.revisionReminder}
              </p>
            ) : isCurrent(row) ? (
              <div className="mt-3 text-sm text-amber-700 dark:text-amber-400">
                <p>AI reminder pending. The study target is already visible to students; this only adds the revision line.</p>
                <button type="button" disabled={!!generatingId || busy} onClick={() => generateReminder(row.id)}
                  className="mt-2 px-3 py-2 rounded-lg border border-amber-300 font-semibold disabled:opacity-60">
                  {generatingId === row.id ? 'Generating AI reminder...' : 'Generate AI reminder'}
                </button>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-400 dark:text-slate-500">No AI reminder for a date that has passed — nothing to fix here.</p>
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
