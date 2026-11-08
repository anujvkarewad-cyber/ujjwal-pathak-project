import { useCallback, useEffect, useState } from 'react';
import { Inbox, RefreshCw, Upload, SkipForward, FileText, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { getInbox, publishInboxFile, skipInboxFile } from '@/api/notesInbox';
import { SERIES_OPTIONS, chaptersForSubject } from '@/constants/chapters';
import { ENROLLMENT_BATCHES } from '@/constants/batches';

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

const BATCHES = ENROLLMENT_BATCHES;
const GROUPS = ['Group 1', 'Group 2', 'Both Groups'];
const SUBJECTS = ['Accounts', 'Law', 'DT', 'GST', 'Costing', 'Audit', 'FM', 'SM'];

const mb = (bytes) => `${(Number(bytes || 0) / 1048576).toFixed(2)} MB`;

export default function NotesInbox() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [done, setDone] = useState('');

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

  useEffect(() => { load(); }, [load]);

  const current = files[0] || null;

  const toggleBatch = (b) =>
    setBatches((prev) => (prev.includes(b) ? prev.filter((x) => x !== b) : [...prev, b]));

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
      await load();
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
        <button onClick={load} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-600 hover:bg-slate-50">
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
    </div>
  );
}
