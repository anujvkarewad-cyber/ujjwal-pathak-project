import { useCallback, useEffect, useState } from 'react';
import { Inbox, RefreshCw, Upload, SkipForward, FileText, AlertTriangle, CheckCircle2, Pencil, Check } from 'lucide-react';
import { getInbox, publishInboxFile, skipInboxFile } from '@/api/notesInbox';
import { getNotes, updateNote } from '@/api/notes';
import { ALL_BATCHES } from '@/constants/batches';
import { SERIES_OPTIONS, chaptersForSubject } from '@/constants/chapters';

// Series = the folder students see inside the subject ("Super 75" or a
// teacher's name). Chapter = the ICAI chapter label; the app shows files of a
// series chapter-wise (Ch 1, Ch 2, …) — no app update needed.
const SERIES_STORAGE_KEY = 'upm_note_series';
const loadSavedSeries = () => {
  try {
    const raw = JSON.parse(localStorage.getItem(SERIES_STORAGE_KEY) || '[]');
    return Array.isArray(raw) ? raw.filter((x) => typeof x === 'string' && x.trim()) : [];
  } catch {
    return [];
  }
};

const BATCHES = [
  'Before Result Batch 1',
  'Before Result Batch 2',
  'After Result Batch 1',
  'After Result Batch 2',
];
const GROUPS = ['Group 1', 'Group 2', 'Both Groups'];
const SUBJECTS = ['Accounts', 'Law', 'DT', 'GST', 'Costing', 'Audit', 'FM', 'SM'];

const mb = (bytes) => `${(Number(bytes || 0) / 1048576).toFixed(2)} MB`;

export default function NotesInbox() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [done, setDone] = useState('');
  const [publishedNotes, setPublishedNotes] = useState([]);
  const [publishedLoading, setPublishedLoading] = useState(true);
  const [publishedError, setPublishedError] = useState('');
  const [editingPublished, setEditingPublished] = useState(null);
  const [savingPublishedEdit, setSavingPublishedEdit] = useState(false);
  const [publishedEditError, setPublishedEditError] = useState('');

  const [batches, setBatches] = useState([BATCHES[0]]);
  const [group, setGroup] = useState(GROUPS[2]);
  const [subject, setSubject] = useState(SUBJECTS[0]);
  const [series, setSeries] = useState(SERIES_OPTIONS[0]);
  const [customSeries, setCustomSeries] = useState('');
  const [chapter, setChapter] = useState('');
  const [savedSeries, setSavedSeries] = useState(loadSavedSeries);

  const seriesOptions = Array.from(new Set([...SERIES_OPTIONS, ...savedSeries]));
  const effectiveSeries = series === '__other__' ? customSeries.trim() : series;
  const chapterGroups = chaptersForSubject(subject);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await getInbox();
      setFiles(data?.files || []);
    } catch (e) {
      setError(e?.message || 'Could not load the inbox.');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPublished = useCallback(async () => {
    setPublishedLoading(true);
    setPublishedError('');
    try {
      const rows = await getNotes();
      setPublishedNotes(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setPublishedError(e?.message || 'Could not load published notes.');
    } finally {
      setPublishedLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    loadPublished();
  }, [load, loadPublished]);

  const current = files[0] || null;

  const toggleBatch = (b) =>
    setBatches((prev) => (prev.includes(b) ? prev.filter((x) => x !== b) : [...prev, b]));

  const startEditPublished = (note) => {
    setPublishedEditError('');
    setEditingPublished({
      id: note.id,
      title: note.title || note.fileName || note.name || 'Published note',
      batches: Array.isArray(note.batches) && note.batches.length
        ? [...note.batches]
        : [note.audience || ALL_BATCHES],
      group: note.group || GROUPS[2],
    });
  };

  const togglePublishedBatch = (batch) => setEditingPublished((currentEdit) => {
    if (!currentEdit) return currentEdit;
    const selected = Array.isArray(currentEdit.batches) ? currentEdit.batches : [];
    if (batch === ALL_BATCHES) {
      return { ...currentEdit, batches: selected.includes(ALL_BATCHES) ? [] : [ALL_BATCHES] };
    }
    const specific = selected.filter((value) => value !== ALL_BATCHES);
    return {
      ...currentEdit,
      batches: specific.includes(batch)
        ? specific.filter((value) => value !== batch)
        : [...specific, batch],
    };
  });

  const savePublishedEdit = async () => {
    if (!editingPublished) return;
    if (!editingPublished.batches.length) {
      setPublishedEditError('Kam se kam ek batch chunein.');
      return;
    }
    const audience = editingPublished.batches.includes(ALL_BATCHES)
      ? { audience: ALL_BATCHES }
      : { batches: editingPublished.batches };
    setSavingPublishedEdit(true);
    setPublishedEditError('');
    try {
      await updateNote(editingPublished.id, {
        ...audience,
        group: editingPublished.group,
      });
      setDone(`Updated "${editingPublished.title}". Wahi published file update hui; dobara upload ki zaroorat nahi.`);
      setEditingPublished(null);
      await loadPublished();
    } catch (e) {
      setPublishedEditError(e?.message || 'Published note update nahi ho saka.');
    } finally {
      setSavingPublishedEdit(false);
    }
  };

  const publish = async () => {
    if (!current) return;
    if (!batches.length) { setError('Kam se kam ek batch chunein.'); return; }
    setBusy('publish'); setDone(''); setError('');
    try {
      const seriesName = effectiveSeries || SERIES_OPTIONS[0];
      await publishInboxFile({
        fileId: current.id,
        batches,
        group,
        subject,
        title: '',
        series: seriesName,
        chapter,
      });
      if (series === '__other__' && customSeries.trim()) {
        const next = Array.from(new Set([...savedSeries, customSeries.trim()])).slice(0, 20);
        setSavedSeries(next);
        try { localStorage.setItem(SERIES_STORAGE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
        setCustomSeries('');
        setSeries(SERIES_OPTIONS[0]);
      }
      setDone(
        `Published "${current.name}" → ${subject}` +
        (chapter ? ` · ${chapter}` : '') +
        ` · ${seriesName}` +
        ` (${batches.length} batch${batches.length === 1 ? '' : 'es'}, ${group}).`,
      );
      await Promise.all([load(), loadPublished()]);
    } catch (e) {
      setError(e?.message || 'Publish failed.');
    } finally {
      setBusy('');
    }
  };

  const skip = async () => {
    if (!current) return;
    setBusy('skip'); setDone(''); setError('');
    try {
      await skipInboxFile(current.id);
      setDone(`"${current.name}" skip kar di gayi.`);
      await load();
    } catch (e) {
      setError(e?.message || 'Skip fail hua.');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-indigo-50 text-indigo-600"><Inbox size={22} /></div>
          <div>
            <h1 className="text-xl font-bold text-slate-800">Notes Inbox</h1>
            <p className="text-sm text-slate-500">
              {loading ? 'Loading…' : `${files.length} file(s) waiting`}
            </p>
          </div>
        </div>
        <button onClick={() => { load(); loadPublished(); }} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50">
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {done && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-emerald-50 text-emerald-700 text-sm">
          <CheckCircle2 size={18} className="mt-0.5 shrink-0" /> {done}
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 text-red-700 text-sm">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {!loading && !current && !error && (
        <div className="p-10 rounded-xl border border-dashed border-slate-300 text-center text-slate-500">
          <Inbox size={32} className="mx-auto mb-2 text-slate-400" />
          Inbox is empty — no files waiting.
        </div>
      )}

      {current && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm p-5 space-y-5">
          <div className="flex items-center gap-3 p-3 rounded-lg bg-slate-50 border border-slate-200">
            <FileText size={20} className="text-indigo-600 shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-800 truncate">Name of file: {current.name}</div>
              <div className="text-xs text-slate-500">{mb(current.size)} · {new Date(current.modifiedTime).toLocaleString('en-IN')}</div>
            </div>
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">Batches <span className="text-red-500">*</span></div>
            <div className="flex flex-wrap gap-2">
              {BATCHES.map((b) => (
                <label key={b} className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer ${batches.includes(b) ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-slate-200 text-slate-600'}`}>
                  <input type="checkbox" checked={batches.includes(b)} onChange={() => toggleBatch(b)} className="accent-indigo-600" />
                  {b}
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">Groups</div>
            <div className="flex flex-wrap gap-2">
              {GROUPS.map((g) => (
                <label key={g} className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer ${group === g ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-slate-200 text-slate-600'}`}>
                  <input type="radio" name="grp" checked={group === g} onChange={() => setGroup(g)} className="accent-indigo-600" />
                  {g === 'Both Groups' ? 'Both' : g}
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">Subject</div>
            <div className="flex flex-wrap gap-2">
              {SUBJECTS.map((s) => (
                <button key={s} onClick={() => { setSubject(s); setChapter(''); }}
                  className={`px-3 py-2 rounded-lg border text-sm ${subject === s ? 'border-indigo-400 bg-indigo-600 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">
              Series / Teacher <span className="text-xs font-normal text-slate-400">(app me folder: Super 75 ya teacher ka naam)</span>
            </div>
            <div className="flex flex-wrap gap-2 items-center">
              {seriesOptions.map((sName) => (
                <button key={sName} onClick={() => setSeries(sName)}
                  className={`px-3 py-2 rounded-lg border text-sm ${series === sName ? 'border-indigo-400 bg-indigo-600 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                  {sName}
                </button>
              ))}
              <button onClick={() => setSeries('__other__')}
                className={`px-3 py-2 rounded-lg border text-sm ${series === '__other__' ? 'border-indigo-400 bg-indigo-600 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                + Teacher ka naam
              </button>
              {series === '__other__' && (
                <input
                  autoFocus
                  value={customSeries}
                  onChange={(e) => setCustomSeries(e.target.value)}
                  placeholder="e.g. CA Rahul Sharma"
                  className="px-3 py-2 rounded-lg border border-indigo-300 text-sm w-52 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
              )}
            </div>
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-700 mb-2">
              Chapter <span className="text-xs font-normal text-slate-400">(note ke naam me "Ch 1 ·", "Ch 2 ·" lagega)</span>
            </div>
            <select
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
            >
              <option value="">— No chapter —</option>
              {chapterGroups.map((c) => (
                <option key={`${c.module}-${c.value}`} value={c.value}>
                  {c.module} · {c.value}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-3 pt-1">
            <button onClick={publish} disabled={!!busy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50">
              <Upload size={16} /> {busy === 'publish' ? 'Publishing…' : 'Publish'}
            </button>
            <button onClick={skip} disabled={!!busy}
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">
              <SkipForward size={16} /> Skip
            </button>
            {files.length > 1 && <span className="text-xs text-slate-400">Queue me {files.length - 1} aur file(s)</span>}
          </div>
        </div>
      )}

      <section className="space-y-3 border-t border-slate-200 pt-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-800">
              Published files <span className="text-sm font-medium text-slate-400">({publishedNotes.length})</span>
            </h2>
            <p className="text-sm text-slate-500">
              Published notes stay here. Edit the audience to add batches without uploading the file again.
            </p>
          </div>
          <button
            type="button"
            onClick={loadPublished}
            className="shrink-0 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50"
          >
            Refresh published
          </button>
        </div>

        {publishedError && (
          <div role="alert" className="p-3 rounded-lg bg-red-50 text-red-700 text-sm">
            {publishedError}
          </div>
        )}
        {publishedLoading && (
          <div role="status" className="p-4 rounded-lg border border-slate-200 text-sm text-slate-500">
            Loading published files…
          </div>
        )}
        {!publishedLoading && !publishedError && publishedNotes.length === 0 && (
          <div className="p-8 rounded-xl border border-dashed border-slate-300 text-center text-slate-500">
            No files have been published yet.
          </div>
        )}

        <div className="space-y-3">
          {publishedNotes.map((note, index) => {
            const noteId = note.id || note.fileId || `published-${index}`;
            const title = note.title || note.fileName || note.name || 'Untitled published note';
            const selected = Array.isArray(note.batches) && note.batches.length
              ? note.batches
              : [note.audience || ALL_BATCHES];
            const batchSummary = selected.includes(ALL_BATCHES) ? ALL_BATCHES : selected.join(', ');
            const fileUrl = note.fileUrl || note.url || '';
            const details = [note.subject, note.group, note.series || note.category, note.chapter]
              .filter(Boolean)
              .join(' · ');
            const isEditing = editingPublished?.id === note.id;

            return (
              <article
                key={note.id || note.fileId || index}
                data-testid={`published-note-${noteId}`}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3"
              >
                <div className="flex flex-wrap items-start gap-3">
                  <FileText size={20} className="mt-0.5 shrink-0 text-indigo-600" />
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-slate-800 break-words">{title}</div>
                    <div className="mt-1 text-xs text-slate-500">Batches: {batchSummary}</div>
                    {details && <div className="mt-1 text-xs text-slate-500">{details}</div>}
                  </div>
                  <div className="flex items-center gap-2">
                    {fileUrl && (
                      <a
                        href={fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="px-3 py-2 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-slate-50"
                      >
                        Open file
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        if (isEditing) {
                          setEditingPublished(null);
                          setPublishedEditError('');
                        } else {
                          startEditPublished(note);
                        }
                      }}
                      disabled={!note.id || savingPublishedEdit}
                      aria-label={`Edit published note ${title}`}
                      data-testid={`edit-published-${noteId}`}
                      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-indigo-200 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
                    >
                      <Pencil size={14} /> {isEditing ? 'Close' : 'Edit audience'}
                    </button>
                  </div>
                </div>

                {isEditing && (
                  <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-4 space-y-4">
                    <div>
                      <div className="text-sm font-semibold text-slate-700">Batches for this file</div>
                      <p className="text-xs text-slate-500 mt-0.5">
                        Keep the current batch selected and tick another one to share this same file with both.
                      </p>
                      <div role="group" aria-label={`Published note batches ${noteId}`} className="mt-2 flex flex-wrap gap-2">
                        {[ALL_BATCHES, ...BATCHES].map((batch) => (
                          <label
                            key={batch}
                            className={`inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs cursor-pointer ${editingPublished.batches.includes(batch) ? 'border-indigo-400 bg-indigo-50 text-indigo-700' : 'border-slate-200 bg-white text-slate-600'}`}
                          >
                            <input
                              type="checkbox"
                              checked={editingPublished.batches.includes(batch)}
                              onChange={() => togglePublishedBatch(batch)}
                              data-testid={`published-batch-${noteId}-${batch}`}
                              className="accent-indigo-600"
                            />
                            {batch}
                          </label>
                        ))}
                      </div>
                      {!editingPublished.batches.length && (
                        <div className="mt-1 text-xs text-amber-700">Choose at least one batch.</div>
                      )}
                    </div>

                    <div>
                      <div className="text-sm font-semibold text-slate-700">Groups</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {GROUPS.map((option) => (
                          <label key={option} className="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-xs text-slate-600 cursor-pointer">
                            <input
                              type="radio"
                              name={`published-group-${noteId}`}
                              checked={editingPublished.group === option}
                              onChange={() => setEditingPublished((value) => ({ ...value, group: option }))}
                              data-testid={`published-group-${noteId}-${option}`}
                              className="accent-indigo-600"
                            />
                            {option}
                          </label>
                        ))}
                      </div>
                    </div>

                    {publishedEditError && (
                      <div role="alert" className="text-xs text-red-700">{publishedEditError}</div>
                    )}
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={savePublishedEdit}
                        disabled={savingPublishedEdit || !editingPublished.batches.length}
                        data-testid={`save-published-${noteId}`}
                        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-50"
                      >
                        <Check size={14} /> {savingPublishedEdit ? 'Saving…' : 'Save changes'}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setEditingPublished(null); setPublishedEditError(''); }}
                        disabled={savingPublishedEdit}
                        className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-600"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
