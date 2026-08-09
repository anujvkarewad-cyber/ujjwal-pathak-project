import { useRef, useState } from 'react';
import { FileText, UploadCloud, FolderUp, Trash2, Download, Users, Calendar, X, Gauge } from 'lucide-react';
import { useNotes, useDeleteNote } from '@/api/hooks';
import { createNoteWithProgress } from '@/api/notes';
import { useQueryClient } from '@tanstack/react-query';
import { Skeleton } from '@/components/common/Skeleton';

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

export default function Notes() {
  const { data: notes = [], isLoading } = useNotes();
  const deleteMut = useDeleteNote();
  const queryClient = useQueryClient();
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);

  const [description, setDescription] = useState('');
  const [subject, setSubject] = useState(SUBJECTS[0]);
  const [group, setGroup] = useState(SUBJECT_GROUP_MAP[SUBJECTS[0]]);
  const [audience, setAudience] = useState('All Batches');
  const [files, setFiles] = useState([]); // File[]
  const [error, setError] = useState('');

  // batch: { fileIndex, fileCount, fileName, fileLoaded, fileTotal, speedBps, batchLoaded, batchTotal, done }
  const [batch, setBatch] = useState(null);
  const isUploading = !!batch && !batch.done;

  const resetForm = () => {
    setDescription('');
    setSubject(SUBJECTS[0]);
    setGroup(SUBJECT_GROUP_MAP[SUBJECTS[0]]);
    setAudience('All Batches');
    setFiles([]);
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
  const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));

  const upload = async (e) => {
    e.preventDefault();
    setError('');
    if (files.length === 0) { setError('Please choose at least one PDF file.'); return; }

    const batchTotal = files.reduce((a, f) => a + f.size, 0);
    let bytesDoneBefore = 0; // sum of sizes of files already fully uploaded

    setBatch({
      fileIndex: 0, fileCount: files.length, fileName: files[0].name,
      fileLoaded: 0, fileTotal: files[0].size,
      speedBps: 0, batchLoaded: 0, batchTotal, done: false,
    });

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      try {
        const fileData = await fileToBase64(file);
        await createNoteWithProgress(
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
            setBatch(prev => prev && ({
              ...prev,
              fileIndex: i,
              fileName: file.name,
              fileLoaded: p.loaded,
              fileTotal: p.total,
              speedBps: p.speedBps ?? prev.speedBps,
              batchLoaded: bytesDoneBefore + p.loaded,
            }));
          }
        );
        bytesDoneBefore += file.size;
      } catch (err) {
        setError(`Failed on "${file.name}": ${err?.message || 'upload error'}. Stopped — already-uploaded files are saved.`);
        setBatch(null);
        queryClient.invalidateQueries({ queryKey: ['notes'] });
        return;
      }
    }

    setBatch(prev => prev && ({ ...prev, batchLoaded: batchTotal, done: true }));
    queryClient.invalidateQueries({ queryKey: ['notes'] });
    setTimeout(resetForm, 900);
  };

  const totalSize = files.reduce((a, f) => a + f.size, 0);
  const batchPercent = batch ? Math.round((batch.batchLoaded / Math.max(1, batch.batchTotal)) * 100) : 0;
  const etaSec = batch && batch.speedBps ? Math.max(0, Math.round((batch.batchTotal - batch.batchLoaded) / batch.speedBps)) : null;

  return (
    <div className="space-y-6" data-testid="notes-page">
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
            disabled={isUploading}
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
            disabled={isUploading}
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200 resize-none disabled:opacity-60"
          />

          <select
            data-testid="note-audience"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            disabled={isUploading}
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB] disabled:opacity-60"
          >
            {['All Batches', 'Super 30', 'Super 11', 'Last 16 Days', 'Last 30 Days'].map(o => <option key={o}>{o}</option>)}
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
                type="file" accept="application/pdf" multiple
                onChange={onFileChange} className="hidden"
              />
              <input
                id="note-folder" ref={folderInputRef} data-testid="note-folder"
                type="file" webkitdirectory="" directory="" multiple
                onChange={onFolderChange} className="hidden"
              />
              <p className="text-[11px] text-slate-400 -mt-1">Folder picker works on desktop browsers (Chrome/Edge).</p>
            </>
          )}

          {/* Selected files list (before upload starts) */}
          {!isUploading && files.length > 0 && (
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg divide-y divide-slate-100 dark:divide-slate-800 max-h-48 overflow-y-auto">
              {files.map((f, idx) => (
                <div key={f.name + f.size + idx} className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                  <span className="truncate text-slate-700 dark:text-slate-300">{titleFromFilename(f.name)}</span>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-slate-400">{formatSize(f.size)}</span>
                    <button type="button" onClick={() => removeFile(idx)} className="text-slate-400 hover:text-red-600">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {!isUploading && files.length > 0 && (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              {files.length} file{files.length > 1 ? 's' : ''} selected · {formatSize(totalSize)} total
            </div>
          )}

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
              className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
            >
              <UploadCloud className="w-4 h-4" />
              {files.length > 1 ? `Upload ${files.length} Notes` : 'Upload Note'}
            </button>
          )}
        </form>

        {/* Notes list */}
        <div className="lg:col-span-2 space-y-3">
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
                        onClick={() => deleteMut.mutate(n.id)}
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
                    <span className="inline-flex items-center gap-1"><Users className="w-3 h-3" />{n.audience}</span>
                    <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">{n.group}</span>
                    <span className="inline-flex items-center gap-1"><Calendar className="w-3 h-3" />{n.date}</span>
                    <span>{n.fileName} · {formatSize(n.fileSize)}</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
