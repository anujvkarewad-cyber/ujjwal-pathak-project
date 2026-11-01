import { useEffect, useRef, useState } from 'react';
import NotesPreparation from '@/components/notes/NotesPreparation';
import { prepareNote, originalEntry, selectedNoteFile, preparedMatches, preparationWithinBudget } from '@/api/notePreparation';
import { FileText, UploadCloud, FolderUp, Trash2, Download, Users, Calendar, X, Gauge, Pencil, Check, Layers, ListChecks } from 'lucide-react';
import { useNotes, useDeleteNote, useUpdateNote } from '@/api/hooks';
import { createNoteChunked, bulkUpdateNotes } from '@/api/notes';
import { SERIES_OPTIONS, chaptersForSubject } from '@/constants/chapters';
import { useQueryClient } from '@tanstack/react-query';
import { Skeleton } from '@/components/common/Skeleton';
import { normalizeStudentGroup } from '@/utils/studentGroup';
import { ALL_BATCHES, ENROLLMENT_BATCHES } from '@/constants/batches';

const MAX_FILE_MB = 20;
const SUBJECT_GROUP_MAP = {
  'Costing': 'Group 2',
  'Audit': 'Group 2',
  'FM': 'Group 2',
  'SM': 'Group 2',
  'Accounts': 'Group 1',
  'Law': 'Group 1',
  'DT': 'Group 1',
  'GST': 'Group 1',
};
const SUBJECTS = Object.keys(SUBJECT_GROUP_MAP);

function formatSize(bytes) {
  if (!bytes) return '0 KB';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec || bytesPerSec <= 0) return '—';
  const mbps = bytesPerSec / (1024 * 1024);
  if (mbps >= 1) return `${mbps.toFixed(1)} MB/s`;
  const kbps = bytesPerSec / 1024;
  return `${Math.round(kbps)} KB/s`;
}

// "Costing_Chapter-4_Notes.pdf" → "Costing Chapter 4 Notes"
function titleFromFilename(name) {
  return name
    .replace(/\.pdf$/i, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = String(reader.result).split(',')[1] || '';
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const GROUP_OPTIONS = ['Group 1', 'Group 2', 'Both Groups'];

export default function Notes({ scopedBatch, scopedGroup } = {}) {
  const { data: allNotes = [], isLoading, error: notesLoadError } = useNotes();
  const notes = allNotes.filter(n => (!scopedBatch || !n.audience || n.audience === ALL_BATCHES || n.audience === scopedBatch) && (!scopedGroup || normalizeStudentGroup(scopedGroup) === 'both' || !n.group || normalizeStudentGroup(n.group) === 'both' || normalizeStudentGroup(n.group) === normalizeStudentGroup(scopedGroup)));
  const deleteMut = useDeleteNote();
  const updateMut = useUpdateNote();
  const queryClient = useQueryClient();

  // Inline editor: null = closed, otherwise the note being edited.
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState('');

  // Bulk chapter/series assign — purane notes ko chapter-wise divide karne ka
  // fast tarika: notes tick karo → chapter chuno → Apply.
  const [bulkMode, setBulkMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkSeries, setBulkSeries] = useState('');
  const [bulkChapter, setBulkChapter] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkNote, setBulkNote] = useState('');

  const toggleSelected = (id) =>
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const applyBulk = async () => {
    if (!selectedIds.length) { setBulkNote('Pehle notes tick karo.'); return; }
    if (!bulkSeries && !bulkChapter) { setBulkNote('Series ya chapter me se kuch chuno.'); return; }
    setBulkBusy(true);
    setBulkNote('');
    try {
      const res = await bulkUpdateNotes({
        ids: selectedIds,
        ...(bulkSeries ? { series: bulkSeries } : {}),
        ...(bulkChapter ? { chapter: bulkChapter } : {}),
      });
      setBulkNote(`${res?.updatedCount ?? selectedIds.length} note(s) update ho gaye — students ko turant dikhega.`);
      setSelectedIds([]);
      await queryClient.invalidateQueries({ queryKey: ['notes'] });
    } catch (err) {
      setBulkNote(err?.message || 'Bulk update fail hua.');
    } finally {
      setBulkBusy(false);
    }
  };

  const startEdit = (n) => {
    setEditError('');
    setEditing({
      id: n.id,
      title: n.title || '',
      description: n.description || '',
      subject: n.subject || '',
      group: n.group || 'Both Groups',
      audience: n.audience || ALL_BATCHES,
      series: n.series || '',
      chapter: n.chapter || n.category || '',
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSavingEdit(true);
    setEditError('');
    try {
      await updateMut.mutateAsync({
        id: editing.id,
        title: editing.title,
        description: editing.description,
        subject: editing.subject,
        group: editing.group,
        audience: editing.audience,
        series: editing.series,
        chapter: editing.chapter,
      });
      setEditing(null);
    } catch (err) {
      setEditError(err?.message || 'Could not save the changes.');
    } finally {
      setSavingEdit(false);
    }
  };
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  const [description, setDescription] = useState('');
  const [subject, setSubject] = useState(SUBJECTS[0]);
  const [group, setGroup] = useState(SUBJECT_GROUP_MAP[SUBJECTS[0]]);
  const [audience, setAudience] = useState(scopedBatch || ALL_BATCHES);
  const [files, setFiles] = useState([]); // File[]
  const [error, setError] = useState('');
  const [quality, setQuality] = useState('balanced');
  const [prepared, setPrepared] = useState([]);
  const [preparing, setPreparing] = useState(null);
  const [uploadResults, setUploadResults] = useState([]);
  const prepareAbort = useRef(null);
  useEffect(() => () => prepareAbort.current?.abort(), []);
  const ready = quality === 'original' || preparedMatches(files, prepared);
  const prepareFiles = async () => {
    if (prepareAbort.current || isUploading || !files.length) return;
    if (!preparationWithinBudget(files)) { setError('Prepare at most 25 PDFs / 100 MB per batch, or choose Original quality.'); return; }
    setError('');
    const controller = new AbortController();
    prepareAbort.current = controller;
    setPrepared([]);
    const result = [];
    try {
      for (let i = 0; i < files.length; i++) {
        setPreparing({ index: i + 1, total: files.length });
        result.push(await prepareNote(files[i], { signal: controller.signal }));
      }
      if (!controller.signal.aborted) setPrepared(result);
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message || 'Preparation stopped. Nothing was published.');
    } finally {
      if (!controller.signal.aborted) setPreparing(null);
      prepareAbort.current = null;
    }
  };


  // batch: { fileIndex, fileCount, fileName, fileLoaded, fileTotal, speedBps, batchLoaded, batchTotal, done }
  const [batch, setBatch] = useState(null);
  const isUploading = !!batch && !batch.done;

  const resetForm = () => {
    setDescription('');
    setSubject(SUBJECTS[0]);
    setGroup(SUBJECT_GROUP_MAP[SUBJECTS[0]]);
    setAudience(ALL_BATCHES);
    setFiles([]);
    setPrepared([]);
    setBatch(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (folderInputRef.current) folderInputRef.current.value = '';
  };

  const onSubjectChange = (e) => {
    const s = e.target.value;
    setSubject(s);
    setGroup(SUBJECT_GROUP_MAP[s] || 'Both Groups');
  };

  const addFiles = (fileList) => {
    if (isUploading || preparing) return;
    setPrepared([]);
    setError('');
    const incoming = Array.from(fileList || []);
    const pdfs = incoming.filter(f => f.type === 'application/pdf' || /\.pdf$/i.test(f.name));
    const skippedNonPdf = incoming.length - pdfs.length;

    const tooBig = pdfs.filter(f => f.size > MAX_FILE_MB * 1024 * 1024);
    const okFiles = pdfs.filter(f => f.size <= MAX_FILE_MB * 1024 * 1024);

    setFiles(prev => {
      const existingKeys = new Set(prev.map(f => f.name + f.size));
      const deduped = okFiles.filter(f => !existingKeys.has(f.name + f.size));
      return [...prev, ...deduped];
    });

    const msgs = [];
    if (skippedNonPdf > 0) msgs.push(`${skippedNonPdf} non-PDF file(s) skipped.`);
    if (tooBig.length > 0) msgs.push(`${tooBig.length} file(s) over ${MAX_FILE_MB}MB skipped.`);
    if (msgs.length) setError(msgs.join(' '));
  };

  const onFileChange = (e) => addFiles(e.target.files);
  const onFolderChange = (e) => addFiles(e.target.files);
  const removeFile = (idx) => {
    setFiles(prev => prev.filter((_, i) => i !== idx));
    setPrepared(prev => prev.filter((_, i) => i !== idx));
  };

  const upload = async (e) => {
    e.preventDefault();
    setError('');
    if (scopedGroup && normalizeStudentGroup(scopedGroup) !== 'both' && normalizeStudentGroup(group) !== normalizeStudentGroup(scopedGroup)) { setError('This subject belongs to a different group. Choose the correct workspace before uploading.'); return; }
    if (files.length === 0) { setError('Please choose at least one PDF file.'); return; }

    if (isUploading || preparing || !ready) { setError('Prepare PDFs first, or choose Original quality.'); return; }
    const entries = quality === 'original' ? files.map(file => originalEntry(file)) : prepared;
    const uploadFiles = entries.map(selectedNoteFile);
    setUploadResults([]);
    const batchTotal = uploadFiles.reduce((a, f) => a + f.size, 0);
    let bytesDoneBefore = 0; // sum of sizes of files already fully uploaded

    setBatch({
      fileIndex: 0, fileCount: files.length, fileName: files[0].name,
      fileLoaded: 0, fileTotal: uploadFiles[0].size,
      speedBps: 0, batchLoaded: 0, batchTotal, done: false,
    });

    for (let i = 0; i < files.length; i++) {
      const file = uploadFiles[i];

      // Speed tracking is done here (client-side, per file) rather than
      // inside createNoteChunked, since chunk-upload progress ticks are
      // per-chunk, not per-byte — this smooths that into a speed estimate
      // similar to what the old single-shot XHR gave us.
      let lastLoaded = 0;
      let lastTime = Date.now();

      try {
        const fileData = await fileToBase64(file);
        await createNoteChunked(
          {
            title: titleFromFilename(file.name),
            description: description.trim(),
            subject: subject.trim(),
            audience,
            group,
            fileName: file.name,
            mimeType: file.type || 'application/pdf',
            fileData,
          },
          (p) => {
            const now = Date.now();
            const elapsedSec = (now - lastTime) / 1000;
            const deltaBytes = p.loaded - lastLoaded;
            const speedBps = elapsedSec > 0.15 ? deltaBytes / elapsedSec : null;
            if (speedBps !== null) {
              lastLoaded = p.loaded;
              lastTime = now;
            }

            setBatch(prev => prev && ({
              ...prev,
              fileIndex: i,
              fileName: file.name,
              fileLoaded: p.loaded,
              fileTotal: p.total,
              speedBps: speedBps ?? prev.speedBps,
              batchLoaded: bytesDoneBefore + p.loaded,
            }));
          }
        );
        bytesDoneBefore += file.size;
        setUploadResults(prev => [...prev, { name: file.name, originalBytes: entries[i].original.size, uploadedBytes: file.size }]);
      } catch (err) {
        setError(`Failed on "${file.name}": ${err?.message || 'upload error'}. Stopped — already-uploaded files are saved.`);
        setBatch(null);
        queryClient.invalidateQueries({ queryKey: ['notes'] });
        return;
      }
    }

    setBatch(prev => prev && ({ ...prev, batchLoaded: batchTotal, done: true }));
    queryClient.invalidateQueries({ queryKey: ['notes'] });
    resetForm();
  };

  const batchPercent = batch ? Math.round((batch.batchLoaded / Math.max(1, batch.batchTotal)) * 100) : 0;
  const etaSec = batch && batch.speedBps ? Math.max(0, Math.round((batch.batchTotal - batch.batchLoaded) / batch.speedBps)) : null;

  return (
    <div className="space-y-6" data-testid="notes-page">
      {deleteTarget && <div role="dialog" aria-modal="true" aria-label="Confirm resource deletion" className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4"><div className="w-full max-w-md rounded-xl bg-white p-6 dark:bg-slate-900"><h3 className="font-semibold">Delete resource?</h3><p className="my-3 text-sm">{deleteTarget.title} · {deleteTarget.audience || ALL_BATCHES} · {deleteTarget.group || 'All subject groups'}</p><p className="mb-4 text-xs text-amber-700">This affects the entire resource audience, not only the selected workspace. The underlying Drive file is not erased.</p><div className="flex justify-end gap-3"><button disabled={deleteMut.isPending} onClick={() => setDeleteTarget(null)}>Cancel</button><button className="rounded-lg bg-rose-600 px-3 py-2 text-sm text-white" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}>Confirm delete</button></div>{deleteMut.isError && <p role="alert" className="mt-3 text-xs text-rose-700">{deleteMut.error.message}</p>}</div></div>}
      {notesLoadError && <p role="alert" className="text-sm text-rose-700">{notesLoadError.message || 'Current resource list could not load. No sample data substituted.'}</p>}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Upload form */}
        <form
          onSubmit={upload}
          className="lg:col-span-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-3 h-fit"
          data-testid="create-note"
        >
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Upload Notes</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 -mt-2">
            Select multiple PDFs or a whole folder — titles are taken from file names.
          </p>

          <select
            data-testid="note-subject"
            value={subject}
            onChange={onSubjectChange}
            disabled={isUploading || !!preparing}
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB] disabled:opacity-60"
          >
            {SUBJECTS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="text-xs text-slate-500 dark:text-slate-400 -mt-1">
            Auto-assigned to <b>{group}</b> based on subject
          </div>

          <textarea
            data-testid="note-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Short description (optional, applies to all files in this batch)"
            rows={2}
            disabled={isUploading || !!preparing}
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200 resize-none disabled:opacity-60"
          />

          <select
            data-testid="note-audience"
            disabled={!!scopedBatch}
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            disabled={isUploading || !!preparing}
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB] disabled:opacity-60"
          >
            {[ALL_BATCHES, ...ENROLLMENT_BATCHES].map(o => <option key={o}>{o}</option>)}
          </select>

          {!isUploading && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label
                  htmlFor="note-file"
                  className="flex flex-col items-center justify-center gap-1.5 px-3 py-4 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 cursor-pointer hover:border-[#2563EB] transition-colors text-center"
                >
                  <UploadCloud className="w-5 h-5 text-slate-400" />
                  <span className="text-xs text-slate-600 dark:text-slate-300">Choose PDF(s)</span>
                </label>
                <label
                  htmlFor="note-folder"
                  className="flex flex-col items-center justify-center gap-1.5 px-3 py-4 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 cursor-pointer hover:border-[#2563EB] transition-colors text-center"
                >
                  <FolderUp className="w-5 h-5 text-slate-400" />
                  <span className="text-xs text-slate-600 dark:text-slate-300">Choose Folder</span>
                </label>
              </div>
              <input
                id="note-file" ref={fileInputRef} data-testid="note-file"
                type="file" accept="application/pdf" multiple disabled={!!preparing}
                onChange={onFileChange} className="hidden"
              />
              <input
                id="note-folder" ref={folderInputRef} data-testid="note-folder"
                type="file" webkitdirectory="" directory="" multiple disabled={!!preparing}
                onChange={onFolderChange} className="hidden"
              />
              <p className="text-[11px] text-slate-400 -mt-1">Folder picker works on desktop browsers (Chrome/Edge).</p>
            </>
          )}

          <NotesPreparation files={files} entries={prepared} quality={quality}
            onQuality={value => { setQuality(value); setPrepared([]); }}
            onPrepare={prepareFiles} onToggle={index => setPrepared(prev => prev.map((entry, i) => i === index ? { ...entry, useOriginal: !entry.useOriginal } : entry))}
            onRemove={removeFile} busy={isUploading || !!preparing} progress={preparing} ready={ready} />
          {uploadResults.length > 0 && <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100">
            <strong>Uploaded successfully</strong>
            {uploadResults.map((result, index) => <p key={index} className="mt-1 break-all">{result.name}: {formatSize(result.originalBytes)} → {formatSize(result.uploadedBytes)}</p>)}
          </div>}

          {/* Live upload progress: overall + current file + speed + ETA */}
          {batch && (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 rounded-lg p-3">
              <div className="flex items-center justify-between text-xs font-medium text-slate-700 dark:text-slate-300">
                <span>{batch.done ? 'Upload complete' : `File ${batch.fileIndex + 1} of ${batch.fileCount}`}</span>
                <span>{batchPercent}%</span>
              </div>
              <div className="h-2 w-full bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#2563EB] transition-all duration-150"
                  style={{ width: `${batchPercent}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                <span className="truncate max-w-[55%]">{batch.done ? `${batch.fileCount} file(s) uploaded` : batch.fileName}</span>
                <span>{formatSize(batch.batchLoaded)} / {formatSize(batch.batchTotal)}</span>
              </div>
              {!batch.done && (
                <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <Gauge className="w-3 h-3" /> {formatSpeed(batch.speedBps)}
                  </span>
                  {etaSec !== null && <span>~{etaSec < 60 ? `${etaSec}s` : `${Math.ceil(etaSec / 60)}m`} left</span>}
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {!isUploading && (
            <button
              type="submit"
              data-testid="publish-note"
              disabled={!!preparing || !ready || files.length === 0}
              className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
            >
              <UploadCloud className="w-4 h-4" />
              {files.length > 1 ? `Upload ${files.length} Notes` : 'Upload Note'}
            </button>
          )}
        </form>

        {/* Notes list */}
        <div className="lg:col-span-2 space-y-3">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {scopedBatch ? 'Resources relevant to this cohort under the existing subject-group access rules. Shared resources retain their original audience; edits can affect every student in that audience.' : 'This is the live app list. Editing or deleting a resource affects all students in its existing audience.'}
          </p>

          {/* Bulk chapter assign (purane notes chapter-wise divide karne ke liye) */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => { setBulkMode((v) => !v); setSelectedIds([]); setBulkNote(''); }}
                data-testid="bulk-toggle"
                className={`inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-xs font-semibold border transition-colors ${
                  bulkMode
                    ? 'bg-[#2563EB] text-white border-[#2563EB]'
                    : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-[#2563EB]'
                }`}
              >
                <ListChecks className="w-4 h-4" /> {bulkMode ? 'Bulk assign ON' : 'Bulk chapter assign'}
              </button>
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                Ek saath kai notes ko Series / Chapter do — jaise 15 notes tick karke "Super 75 · Ch 5".
              </span>
            </div>

            {bulkMode && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    list="bulk-series-options"
                    value={bulkSeries}
                    onChange={(e) => setBulkSeries(e.target.value)}
                    placeholder="Series / teacher (e.g. Super 75)"
                    data-testid="bulk-series"
                    className="h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200 outline-none focus:border-[#2563EB] w-56"
                  />
                  <datalist id="bulk-series-options">
                    {Array.from(new Set([...SERIES_OPTIONS, ...notes.map((x) => x.series).filter(Boolean)])).map((sOpt) => (
                      <option key={sOpt} value={sOpt} />
                    ))}
                  </datalist>
                  <select
                    value={bulkChapter}
                    onChange={(e) => setBulkChapter(e.target.value)}
                    data-testid="bulk-chapter"
                    className="h-10 px-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB] max-w-[22rem]"
                  >
                    <option value="">— Chapter nahi badalna —</option>
                    {SUBJECTS.map((subj) => (
                      <optgroup key={subj} label={subj}>
                        {chaptersForSubject(subj).map((c) => (
                          <option key={`${subj}-${c.module}-${c.value}`} value={c.value}>{c.value}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setSelectedIds(notes.map((x) => x.id))}
                    className="h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:border-[#2563EB]"
                  >
                    Select all ({notes.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedIds([])}
                    className="h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300"
                  >
                    Clear
                  </button>
                  <button
                    type="button"
                    onClick={applyBulk}
                    disabled={bulkBusy || !selectedIds.length}
                    data-testid="bulk-apply"
                    className="h-10 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold inline-flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <Check className="w-4 h-4" />
                    {bulkBusy ? 'Saving…' : `Apply to ${selectedIds.length} note${selectedIds.length === 1 ? '' : 's'}`}
                  </button>
                </div>
                {bulkNote && (
                  <div className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">{bulkNote}</div>
                )}
              </>
            )}
          </div>
          {isLoading && <Skeleton className="h-32 w-full" />}
          {!isLoading && notes.length === 0 && (
            <div className="bg-white dark:bg-slate-900 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-sm text-slate-500 dark:text-slate-400">
              No notes uploaded yet. Upload PDFs to make them visible on every student's dashboard.
            </div>
          )}
          {notes.map((n) => (
            <div
              key={n.id}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 rounded-xl p-5 transition-colors"
              data-testid={`note-${n.id}`}
            >
              <div className="flex items-start gap-3">
                {bulkMode && (
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(n.id)}
                    onChange={() => toggleSelected(n.id)}
                    data-testid={`pick-${n.id}`}
                    className="mt-3 w-4 h-4 accent-[#2563EB]"
                  />
                )}
                <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center flex-shrink-0">
                  <FileText className="w-5 h-5 text-[#2563EB]" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <h4 className="font-heading font-semibold text-slate-900 dark:text-white truncate">{n.title}</h4>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <a
                        href={n.fileUrl}
                        target="_blank"
                        rel="noreferrer"
                        data-testid={`download-${n.id}`}
                        className="p-2 rounded-lg text-slate-400 hover:text-[#2563EB] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                        aria-label="Open PDF"
                      >
                        <Download className="w-4 h-4" />
                      </a>
                      <button
                        onClick={() => (editing?.id === n.id ? setEditing(null) : startEdit(n))}
                        data-testid={`edit-${n.id}`}
                        className="p-2 rounded-lg text-slate-400 hover:text-[#2563EB] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                        aria-label="Edit note"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setDeleteTarget(n)}
                        data-testid={`delete-${n.id}`}
                        className="p-2 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors"
                        aria-label="Delete note"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                  {n.description && (
                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{n.description}</p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                    {n.subject && <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">{n.subject}</span>}
                    {(n.category || n.series) && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 font-semibold">
                        <Layers className="w-3 h-3" />{n.category || n.series}
                      </span>
                    )}
                    {n.chapter && (
                      <span className="px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300">{n.chapter}</span>
                    )}
                    <span className="inline-flex items-center gap-1"><Users className="w-3 h-3" />{n.audience}</span>
                    <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">{n.group}</span>
                    <span className="inline-flex items-center gap-1"><Calendar className="w-3 h-3" />{n.date}</span>
                    <span>{n.fileName} · {formatSize(n.fileSize)}</span>
                  </div>

                  {editing?.id === n.id && (
                    <div
                      className="mt-3 border border-slate-200 dark:border-slate-700 rounded-lg p-3 space-y-2 bg-slate-50 dark:bg-slate-800/40"
                      data-testid={`edit-form-${n.id}`}
                    >
                      <input
                        value={editing.title}
                        onChange={(e) => setEditing((p) => ({ ...p, title: e.target.value }))}
                        placeholder="Title"
                        className="w-full h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                      />
                      <textarea
                        value={editing.description}
                        onChange={(e) => setEditing((p) => ({ ...p, description: e.target.value }))}
                        placeholder="Description (optional)"
                        rows={2}
                        className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200 outline-none focus:border-[#2563EB] resize-none"
                      />
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                        <select
                          value={editing.subject}
                          onChange={(e) => setEditing((p) => ({ ...p, subject: e.target.value }))}
                          className="h-10 px-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                        >
                          {Array.from(new Set([...SUBJECTS, editing.subject].filter(Boolean))).map((s) => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                        <select
                          value={editing.group}
                          onChange={(e) => setEditing((p) => ({ ...p, group: e.target.value }))}
                          className="h-10 px-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                        >
                          {Array.from(new Set([...GROUP_OPTIONS, editing.group].filter(Boolean))).map((g) => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                        <select
                          value={editing.audience}
                          onChange={(e) => setEditing((p) => ({ ...p, audience: e.target.value }))}
                          className="h-10 px-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                        >
                          {[ALL_BATCHES, ...ENROLLMENT_BATCHES].map((b) => (
                            <option key={b} value={b}>{b}</option>
                          ))}
                        </select>
                      </div>

                      {/* Series (folder students see) + ICAI chapter */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Series / Teacher <span className="normal-case font-normal">(app me folder banta hai)</span></div>
                          <input
                            list={`series-options-${n.id}`}
                            value={editing.series}
                            onChange={(e) => setEditing((p) => ({ ...p, series: e.target.value }))}
                            placeholder="Super 75, ya teacher ka naam"
                            data-testid={`edit-series-${n.id}`}
                            className="w-full h-10 px-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-800 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                          />
                          <datalist id={`series-options-${n.id}`}>
                            {Array.from(new Set([...SERIES_OPTIONS, ...notes.map((x) => x.series).filter(Boolean)])).map((sOpt) => (
                              <option key={sOpt} value={sOpt} />
                            ))}
                          </datalist>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {Array.from(new Set([...SERIES_OPTIONS, ...notes.map((x) => x.series).filter(Boolean)])).slice(0, 6).map((sOpt) => (
                              <button
                                key={`q-${sOpt}`}
                                type="button"
                                onClick={() => setEditing((p) => ({ ...p, series: sOpt }))}
                                className="px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700 text-[11px] text-slate-600 dark:text-slate-300 hover:border-[#2563EB]"
                              >
                                {sOpt}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Chapter <span className="normal-case font-normal">(note ke naam me "Ch N ·" lagega)</span></div>
                          <select
                            value={editing.chapter || ''}
                            onChange={(e) => setEditing((p) => ({ ...p, chapter: e.target.value }))}
                            data-testid={`edit-chapter-${n.id}`}
                            className="w-full h-10 px-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
                          >
                            <option value="">— No chapter —</option>
                            {chaptersForSubject(editing.subject || n.subject).map((c) => (
                              <option key={`${c.module}-${c.value}`} value={c.value}>
                                {c.module} · {c.value}
                              </option>
                            ))}
                            {editing.chapter && !chaptersForSubject(editing.subject || n.subject).some((c) => c.value === editing.chapter) ? (
                              <option value={editing.chapter}>{editing.chapter} (custom)</option>
                            ) : null}
                          </select>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={saveEdit}
                          disabled={savingEdit}
                          data-testid={`save-${n.id}`}
                          className="h-9 px-3 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-60"
                        >
                          <Check className="w-3.5 h-3.5" /> {savingEdit ? 'Saving…' : 'Save changes'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditing(null)}
                          className="h-9 px-3 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 text-xs font-medium"
                        >
                          Cancel
                        </button>
                        <span className="text-[11px] text-slate-500 dark:text-slate-400">
                          Students see the change right away.
                        </span>
                      </div>
                      {editError && (
                        <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg px-3 py-2">
                          {editError}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
