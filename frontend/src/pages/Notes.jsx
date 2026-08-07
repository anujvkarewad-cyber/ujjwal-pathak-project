import { useRef, useState } from 'react';
import { FileText, UploadCloud, Trash2, Download, Users, Calendar, Paperclip } from 'lucide-react';
import { useNotes, useCreateNote, useDeleteNote } from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';

const MAX_FILE_MB = 20;

function formatSize(bytes) {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result looks like "data:application/pdf;base64,JVBERi0x..."
      const base64 = String(reader.result).split(',')[1] || '';
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function Notes() {
  const { data: notes = [], isLoading } = useNotes();
  const createMut = useCreateNote();
  const deleteMut = useDeleteNote();
  const fileInputRef = useRef(null);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [subject, setSubject] = useState('');
  const [audience, setAudience] = useState('All Batches');
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');

  const resetForm = () => {
    setTitle(''); setDescription(''); setSubject(''); setAudience('All Batches');
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const onFileChange = (e) => {
    const f = e.target.files?.[0];
    setError('');
    if (!f) { setFile(null); return; }
    if (f.type !== 'application/pdf') {
      setError('Only PDF files are supported.');
      setFile(null);
      return;
    }
    if (f.size > MAX_FILE_MB * 1024 * 1024) {
      setError(`File is too large. Max ${MAX_FILE_MB} MB.`);
      setFile(null);
      return;
    }
    setFile(f);
  };

  const upload = async (e) => {
    e.preventDefault();
    setError('');
    if (!title.trim()) { setError('Please add a title.'); return; }
    if (!file) { setError('Please choose a PDF file.'); return; }

    try {
      const fileData = await fileToBase64(file);
      createMut.mutate(
        {
          title: title.trim(),
          description: description.trim(),
          subject: subject.trim(),
          audience,
          fileName: file.name,
          mimeType: file.type,
          fileData,
        },
        {
          onSuccess: resetForm,
          onError: (err) => setError(err?.message || 'Upload failed. Please try again.'),
        }
      );
    } catch (err) {
      setError('Could not read the file. Please try again.');
    }
  };

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
            PDF appears on every student's dashboard instantly.
          </p>

          <input
            data-testid="note-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (e.g. Costing — Chapter 4 Notes)"
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200"
          />
          <input
            data-testid="note-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject (optional)"
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200"
          />
          <textarea
            data-testid="note-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Short description (optional)"
            rows={3}
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200 resize-none"
          />
          <select
            data-testid="note-audience"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
          >
            {['All Batches', 'Super 30', 'Super 11', 'Last 16 Days', 'Last 30 Days'].map(o => <option key={o}>{o}</option>)}
          </select>

          <label
            htmlFor="note-file"
            className="flex items-center gap-3 w-full px-3 py-3 rounded-lg border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 cursor-pointer hover:border-[#2563EB] transition-colors"
          >
            <UploadCloud className="w-5 h-5 text-slate-400 flex-shrink-0" />
            <span className="text-sm text-slate-600 dark:text-slate-300 truncate">
              {file ? file.name : 'Choose PDF file'}
            </span>
          </label>
          <input
            id="note-file"
            ref={fileInputRef}
            data-testid="note-file"
            type="file"
            accept="application/pdf"
            onChange={onFileChange}
            className="hidden"
          />
          {file && (
            <div className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
              <Paperclip className="w-3 h-3" /> {formatSize(file.size)}
            </div>
          )}

          {error && (
            <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={createMut.isPending}
            data-testid="publish-note"
            className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
          >
            <UploadCloud className="w-4 h-4" /> {createMut.isPending ? 'Uploading...' : 'Upload Note'}
          </button>
        </form>

        {/* Notes list */}
        <div className="lg:col-span-2 space-y-3">
          {isLoading && <Skeleton className="h-32 w-full" />}
          {!isLoading && notes.length === 0 && (
            <div className="bg-white dark:bg-slate-900 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center text-sm text-slate-500 dark:text-slate-400">
              No notes uploaded yet. Upload a PDF to make it visible on every student's dashboard.
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
