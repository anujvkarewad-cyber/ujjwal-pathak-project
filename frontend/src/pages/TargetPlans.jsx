import SmartTargetFollow from '../components/SmartTargetFollow';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Ban, CalendarRange, Camera, Pencil, Plus, Save, Trash2 } from 'lucide-react';
import { fetchTargetOptions, previewTargetAudience } from '@/api/dailyTargets';
import {
  cancelTargetPlan,
  editTargetPlanDay,
  fetchTargetPlans,
  parseTargetPlanPhoto,
  publishTargetPlan,
  previewPersonalTargetAudience,
} from '@/api/targetPlans';

const ALL = 'All';
const KINDS = [
  ['study', 'Study'],
  ['revision', 'Revision'],
  ['test', 'Test'],
];
const MAX_DAYS = 90;

const IST_FMT = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' });

function todayIst() {
  const parts = Object.fromEntries(IST_FMT.formatToParts(new Date()).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function addDays(iso, count) {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + count));
  return date.toISOString().slice(0, 10);
}

function displayDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y.slice(2)}`;
}

function blankEntry() {
  return { subject: '', topic: '', hours: '', kind: 'study', customSubject: '' };
}

function blankDay() {
  return { entries: [blankEntry()] };
}

function entryPayload(entry) {
  return {
    subject: entry.subject === 'Other' ? (entry.customSubject || '').trim() : entry.subject,
    topic: (entry.topic || '').trim(),
    hours: entry.hours === '' || entry.hours == null ? null : Number(entry.hours),
    kind: entry.kind,
  };
}

function EntryRows({ entries, onChange, subjectChoices, compact = false }) {
  const patch = (index, changes) =>
    onChange(entries.map((row, i) => (i === index ? { ...row, ...changes } : row)));
  const remove = (index) => onChange(entries.filter((_, i) => i !== index));
  const inputClass = 'h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100';
  return (
    <div className="space-y-2">
      {entries.map((entry, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <select
            value={entry.subject}
            onChange={(e) => patch(index, { subject: e.target.value })}
            className={`${inputClass} min-w-40 flex-1`}
            aria-label="Subject"
          >
            <option value="">Subject…</option>
            {subjectChoices.map((choice) => (
              <option key={choice} value={choice}>{choice === ALL ? 'All (full-day line)' : choice}</option>
            ))}
          </select>
          {entry.subject === 'Other' && (
            <input
              value={entry.customSubject}
              onChange={(e) => patch(index, { customSubject: e.target.value })}
              placeholder="Subject name"
              className={`${inputClass} w-36`}
            />
          )}
          <input
            value={entry.topic}
            onChange={(e) => patch(index, { topic: e.target.value })}
            placeholder="Topic / material, e.g. Chap 1"
            className={`${inputClass} min-w-44 flex-[2]`}
          />
          <input
            type="number"
            min="0"
            max="24"
            step="0.5"
            value={entry.hours}
            onChange={(e) => patch(index, { hours: e.target.value })}
            placeholder="hrs"
            className={`${inputClass} w-20`}
            aria-label="Hours"
          />
          <select
            value={entry.kind}
            onChange={(e) => patch(index, { kind: e.target.value })}
            className={`${inputClass} w-28`}
            aria-label="Type"
          >
            {KINDS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => remove(index)}
            disabled={entries.length === 1}
            className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-30 dark:hover:bg-rose-950/40"
            aria-label="Remove line"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      {!compact && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onChange([...entries, blankEntry()])}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 px-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <Plus className="h-3.5 w-3.5" /> Add line
          </button>
          <button
            type="button"
            onClick={() => onChange([...entries, { ...blankEntry(), subject: ALL, topic: 'Revision (full day)', hours: 1, kind: 'revision' }])}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 px-2.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <Plus className="h-3.5 w-3.5" /> 1 hr revision
          </button>
        </div>
      )}
    </div>
  );
}

export default function TargetPlans() {
  const today = todayIst();
  const [options, setOptions] = useState({ attempts: [], groups: [], batches: [], subjects: [] });
  const [plans, setPlans] = useState([]);
  const [name, setName] = useState('');
  const [mode, setMode] = useState('calendar');
  const [includedBackupDays, setIncludedBackupDays] = useState(1);
  const [revisionBudgetMinutes, setRevisionBudgetMinutes] = useState(30);
  const [startDate, setStartDate] = useState(today);
  const [firstDay, setFirstDay] = useState(1); // Journey day number of the FIRST uploaded day (e.g. 24 when continuing an ongoing plan)
  const [attempt, setAttempt] = useState(ALL);
  const [group, setGroup] = useState(ALL);
  const [batch, setBatch] = useState(ALL);
  const [days, setDays] = useState([blankDay(), blankDay()]);
  const [audience, setAudience] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind: 'ok'|'err', text }
  const [editing, setEditing] = useState(null); // { planId, planName, day, entries }
  const photoInputRef = useRef(null);

  const onPhoto = async (file) => {
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await parseTargetPlanPhoto(file);
      if (res.name) setName(res.name);
      if (res.group) {
        const match = (options.groups || []).find((value) => String(value).toLowerCase().includes(String(res.group).toLowerCase()));
        if (match) setGroup(match);
      }
      setDays(res.days.map((day) => ({
        entries: day.entries.map((entry) => ({
          subject: entry.subject === ALL || (options.subjects || []).includes(entry.subject) ? entry.subject : 'Other',
          customSubject: entry.subject === ALL || (options.subjects || []).includes(entry.subject) ? '' : entry.subject,
          topic: entry.topic || '',
          hours: entry.hours == null ? '' : entry.hours,
          kind: entry.kind || 'study',
        })),
      })));
      setMessage({ kind: 'ok', text: `Photo parsed: ${res.days.length} days filled in. Review the rows below, then press Publish plan.` });
    } catch (err) {
      setMessage({ kind: 'err', text: err.message || 'Photo parse failed.' });
    } finally {
      setBusy(false);
      if (photoInputRef.current) photoInputRef.current.value = '';
    }
  };

  const load = () => fetchTargetPlans().then((res) => setPlans(res.plans || [])).catch((err) => setMessage({ kind: 'err', text: err.message }));

  useEffect(() => {
    fetchTargetOptions().then(setOptions).catch(() => setOptions({ attempts: [], groups: [], batches: [], subjects: [] }));
    load();
  }, []);

  useEffect(() => {
    let alive = true;
    (mode === 'personal' ? previewPersonalTargetAudience : previewTargetAudience)({ attempt, group, batch })
      .then((res) => { if (alive) setAudience(res); })
      .catch(() => { if (alive) setAudience(null); });
    return () => { alive = false; };
  }, [attempt, group, batch, mode]);

  const subjectChoices = useMemo(() => [ALL, ...(options.subjects || []), 'Other'], [options.subjects]);

  const patchDay = (index, entries) =>
    setDays(days.map((row, i) => (i === index ? { entries } : row)));

  const targetCount = useMemo(
    () => days.reduce((total, day) => total + new Set(day.entries.map((entry) => entryPayload(entry).subject).filter(Boolean)).size, 0),
    [days],
  );

  const publish = async () => {
    setMessage(null);
    const offset = Number.isInteger(Number(firstDay)) ? Math.min(Math.max(Number(firstDay), 1), 90) : 1;
    const cleanDays = days
      .map((day, index) => ({
        day: offset + index,
        entries: day.entries.map(entryPayload).filter((entry) => entry.subject && entry.topic),
      }))
      .filter((day) => day.entries.length > 0);
    if (offset + days.length - 1 > 90) return setMessage({ kind: 'err', text: 'Total days cannot go beyond Day 90. Reduce the first-day number or days.' });
    if (!name.trim()) return setMessage({ kind: 'err', text: 'Add a plan name.' });
    if (!cleanDays.length) return setMessage({ kind: 'err', text: 'Fill at least one line in a day.' });
    setBusy(true);
    try {
      const res = await publishTargetPlan({
        name: name.trim(), startDate, attempt, group, batch, days: cleanDays, mode, includedBackupDays: Number(includedBackupDays), revisionBudgetMinutes: Number(revisionBudgetMinutes),
      });
      setMessage({
        kind: 'ok',
        text: mode === 'personal' ? `Personal plan published for ${res.studentCount} students. Each student starts Day ${offset} independently. Sheet mirror: ${res.sheetMirror}.` : `Plan published: ${res.targetsCreated} targets for ${res.studentCount} students. Sheet mirror: ${res.sheetMirror}. AI reminders are generating in the background.`,
      });
      setName('');
      setDays([blankDay(), blankDay()]);
      setFirstDay(1);
      load();
    } catch (err) {
      setMessage({ kind: 'err', text: err.message || 'Publish failed.' });
    } finally {
      setBusy(false);
    }
  };

  const openDayEditor = (plan) => {
    const candidates = (plan.days || []).filter((day) => plan.mode === 'personal' || day.date >= today);
    if (!candidates.length) {
      setMessage({ kind: 'err', text: 'This plan has no upcoming days left to edit.' });
      return;
    }
    const first = candidates[0];
    setEditing({
      planId: plan.id,
      planName: plan.name,
      day: first.day,
      options: candidates.map((day) => day.day),
      entries: (first.entries || []).map((entry) => ({
        subject: (options.subjects || []).includes(entry.subject) || entry.subject === ALL ? entry.subject : 'Other',
        customSubject: (options.subjects || []).includes(entry.subject) || entry.subject === ALL ? '' : entry.subject,
        topic: entry.topic || entry.label || '',
        hours: entry.hours == null ? '' : entry.hours,
        kind: entry.kind || 'study',
      })),
    });
  };

  const saveDayEdit = async () => {
    const entries = editing.entries.map(entryPayload).filter((entry) => entry.subject && entry.topic);
    if (!entries.length) return setMessage({ kind: 'err', text: 'Add at least one filled line for this day.' });
    setBusy(true);
    try {
      const res = await editTargetPlanDay(editing.planId, { day: editing.day, entries });
      setMessage({ kind: 'ok', text: `Day ${editing.day} updated. Sheet mirror: ${res.sheetMirror}.` });
      setEditing(null);
      load();
    } catch (err) {
      setMessage({ kind: 'err', text: err.message || 'Day update failed.' });
    } finally {
      setBusy(false);
    }
  };

  const cancelPlan = async (plan) => {
    if (!window.confirm(`Cancel "${plan.name}"? Targets for upcoming days will be removed; past days remain in history.`)) return;
    setBusy(true);
    try {
      const res = await cancelTargetPlan(plan.id);
      setMessage({ kind: 'ok', text: `Plan cancelled. ${res.deactivatedTargets} upcoming targets removed. Sheet mirror: ${res.sheetMirror}.` });
      load();
    } catch (err) {
      setMessage({ kind: 'err', text: err.message || 'Cancel failed.' });
    } finally {
      setBusy(false);
    }
  };

  const inputClass = 'h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100';
  const labelClass = 'block text-xs font-semibold text-slate-500 dark:text-slate-400';

  return (
    <div className="space-y-6" data-testid="target-plans-page">
      <div>
        <div className="flex items-center gap-2">
          <CalendarRange className="h-5 w-5 text-[#2563EB]" />
          <h1 className="font-heading text-xl font-bold text-slate-900 dark:text-white">Target Plans</h1>
        </div>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Create calendar targets or personal sequences with independent starts, backups and revision follow-up.
        </p>
      </div>

      {message && (
        <div
          role="status"
          className={`rounded-lg border px-4 py-3 text-sm ${message.kind === 'ok' ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300' : 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300'}`}
        >
          {message.text}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900 xl:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-bold text-slate-800 dark:text-slate-100">New plan</div>
              <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                Upload a poster or handwritten plan photo — days, subjects, topics and hours are filled in automatically.
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={photoInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={(event) => onPhoto(event.target.files?.[0])}
                data-testid="plan-photo-input"
              />
              <button
                type="button"
                onClick={() => photoInputRef.current?.click()}
                disabled={busy}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-[#2563EB] px-4 text-sm font-bold text-[#2563EB] hover:bg-blue-50 disabled:opacity-50 dark:hover:bg-blue-950/40"
                data-testid="plan-photo-button"
              >
                <Camera className="h-4 w-4" /> {busy ? 'Reading photo…' : 'Fill from photo'}
              </button>
            </div>
          </div>
          <div className="mb-3 grid gap-3 sm:grid-cols-3">
            <label className="space-y-1"><span className={labelClass}>Delivery mode</span><select aria-label="Delivery mode" value={mode} onChange={e => setMode(e.target.value)} className={`${inputClass} w-full`}><option value="calendar">Calendar (existing mode)</option><option value="personal">Personal sequence — Smart Targets</option></select></label>
            {mode === 'personal' && <><label className="space-y-1"><span className={labelClass}>Included backup days</span><input aria-label="Included backup days" type="number" min="0" max="60" value={includedBackupDays} onChange={e => setIncludedBackupDays(e.target.value)} className={`${inputClass} w-full`} /></label><label className="space-y-1"><span className={labelClass}>Revision budget (minutes/day)</span><input aria-label="Revision budget" type="number" min="10" max="180" value={revisionBudgetMinutes} onChange={e => setRevisionBudgetMinutes(e.target.value)} className={`${inputClass} w-full`} /></label></>}
          </div>
          {mode === 'personal' && <p className="mb-3 text-xs text-slate-500">All entered tasks are mandatory. Each next day opens after the previous day is complete and its adjusted IST date arrives. Backup/extension days add time, never skip unfinished work. Started plans use an immutable snapshot. Revisions remain independent.</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className={labelClass}>Plan name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="CA Inter Super 75" className={`${inputClass} w-full`} />
            </label>
            <label className="space-y-1">
              <span className={labelClass}>{mode === 'personal' ? 'Available for personal starts from' : `Day ${Number(firstDay) || 1} starts on`}</span>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className={`${inputClass} w-full`} />
            </label>
            <label className="space-y-1">
              <span className={labelClass}>First day number</span>
              <input aria-label="First day number" type="number" min="1" max="90" value={firstDay} onChange={(e) => setFirstDay(e.target.value)} className={`${inputClass} w-full`} />
              <span className="block text-xs text-slate-400">Ongoing plan continue karte time: e.g. 24. Naya plan: 1.</span>
            </label>
            <label className="space-y-1">
              <span className={labelClass}>Batch</span>
              <select value={batch} onChange={(e) => setBatch(e.target.value)} className={`${inputClass} w-full`}>
                <option value={ALL}>All Batches</option>
                {(options.batches || []).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1">
                <span className={labelClass}>Group</span>
                <select value={group} onChange={(e) => setGroup(e.target.value)} className={`${inputClass} w-full`}>
                  <option value={ALL}>All</option>
                  {(options.groups || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className={labelClass}>Attempt</span>
                <select value={attempt} onChange={(e) => setAttempt(e.target.value)} className={`${inputClass} w-full`}>
                  <option value={ALL}>All</option>
                  {(options.attempts || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
            </div>
          </div>

          {days.map((day, index) => (
            <div key={index} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100">
                  Day {(Number(firstDay) || 1) + index}
                  <span className="ml-2 text-xs font-semibold text-slate-400">{mode === 'personal' ? 'Personal date after student starts' : displayDate(addDays(startDate, index))}</span>
                </div>
                {days.length > 1 && index === days.length - 1 && (
                  <button type="button" onClick={() => setDays(days.slice(0, -1))} className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/40" aria-label="Remove last day">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              <EntryRows entries={day.entries} onChange={(entries) => patchDay(index, entries)} subjectChoices={subjectChoices} />
            </div>
          ))}

          <div className="flex flex-wrap items-center gap-3">
            {days.length < MAX_DAYS && (
              <button type="button" onClick={() => setDays([...days, blankDay()])} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
                <Plus className="h-4 w-4" /> Add day
              </button>
            )}
            <button
              type="button"
              onClick={publish}
              disabled={busy}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#2563EB] px-5 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-50"
              data-testid="publish-plan"
            >
              <Save className="h-4 w-4" /> {busy ? 'Publishing…' : 'Publish plan'}
            </button>
          </div>
        </section>

        <aside className="space-y-3 rounded-xl border border-blue-100 bg-blue-50/60 p-5 dark:border-blue-900 dark:bg-blue-950/30">
          <div className="text-xs font-bold uppercase tracking-[0.14em] text-blue-800 dark:text-blue-300">Preview</div>
          <div className="text-sm text-slate-700 dark:text-slate-200">
            <b>{audience ? audience.count : '…'}</b> students matched {mode === 'personal' && audience && `· ${audience.readyCount} enrollment-ready · Students Sheet`} ({batch === ALL ? 'All batches' : batch}{group !== ALL ? ` · Group ${group}` : ''}{attempt !== ALL ? ` · Attempt ${attempt}` : ''})
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-200">
            <b>{days.length}</b> days · <b>{targetCount}</b> targets will be created
          </div>
          <div className="text-sm text-slate-700 dark:text-slate-200">
            From {displayDate(startDate)} to {displayDate(addDays(startDate, days.length - 1))}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            On publish, each day's target reaches the students' app immediately. AI revision reminders follow in the background within a minute or two. A copy of every active plan is also written to the “Target Plans” tab of the tracker sheet (best-effort).
          </p>
        </aside>
      </div>

      <section className="space-y-3">
        <h2 className="font-heading text-lg font-bold text-slate-900 dark:text-white">Published plans</h2>
        {plans.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
            No plans published yet.
          </div>
        )}
        {plans.map((plan) => (
          <div key={plan.id} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-900 dark:text-white">{plan.name}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${plan.status === 'active' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
                    {plan.status}
                  </span>
                </div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {plan.batch} · Group {plan.group} · Attempt {plan.attempt} · {displayDate(plan.startDate)} se {(plan.days || []).length} din · {plan.studentCount} students
                </div>
              </div>
              {plan.status === 'active' && (
                <div className="flex gap-2">
                  <button type="button" onClick={() => openDayEditor(plan)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
                    <Pencil className="h-3.5 w-3.5" /> Edit upcoming day
                  </button>
                  <button type="button" onClick={() => cancelPlan(plan)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-rose-200 px-3 text-xs font-semibold text-rose-600 hover:bg-rose-50 dark:border-rose-900 dark:hover:bg-rose-950/40">
                    <Ban className="h-3.5 w-3.5" /> Cancel plan
                  </button>
                </div>
              )}
            </div>
            {plan.mode === 'personal' && <SmartTargetFollow plan={plan} />}
            {editing?.planId === plan.id && (
              <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/60 p-3 dark:border-blue-900 dark:bg-blue-950/30">
                <div className="mb-2 flex items-center gap-3">
                  <label className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                    Day:
                    <select
                      value={editing.day}
                      onChange={(e) => {
                        const day = Number(e.target.value);
                        const source = (plan.days || []).find((row) => row.day === day);
                        setEditing({
                          ...editing,
                          day,
                          entries: (source?.entries || []).map((entry) => ({
                            subject: (options.subjects || []).includes(entry.subject) || entry.subject === ALL ? entry.subject : 'Other',
                            customSubject: (options.subjects || []).includes(entry.subject) || entry.subject === ALL ? '' : entry.subject,
                            topic: entry.topic || entry.label || '',
                            hours: entry.hours == null ? '' : entry.hours,
                            kind: entry.kind || 'study',
                          })),
                        });
                      }}
                      className="ml-2 h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                    >
                      {editing.options.map((day) => (
                        <option key={day} value={day}>Day {day} · {displayDate(addDays(plan.startDate, day - 1))}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <EntryRows entries={editing.entries} onChange={(entries) => setEditing({ ...editing, entries })} subjectChoices={subjectChoices} />
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={saveDayEdit} disabled={busy} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#2563EB] px-4 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-50">
                    <Save className="h-3.5 w-3.5" /> Save day
                  </button>
                  <button type="button" onClick={() => setEditing(null)} className="inline-flex h-9 items-center rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300">
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
