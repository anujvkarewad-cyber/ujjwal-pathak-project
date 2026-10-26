import { useEffect, useState } from 'react';
import { preparationMessage, selectedNoteFile } from '@/api/notePreparation';

const size = bytes => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`;

function PdfLink({ file, label }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return <a href={url || undefined} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline dark:text-blue-300">{label}</a>;
}

export default function NotesPreparation({ files, entries, quality, onQuality, onPrepare, onToggle, onRemove, busy, progress, ready }) {
  return <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900" data-testid="notes-preparation">
    <label className="block text-sm font-semibold text-slate-800 dark:text-slate-100" htmlFor="notes-quality">PDF quality</label>
    <select id="notes-quality" value={quality} disabled={busy} onChange={e => onQuality(e.target.value)} className="w-full rounded-lg border p-2 text-sm bg-white text-slate-900 dark:bg-slate-800 dark:text-white">
      <option value="balanced">Balanced — prepare & review before upload</option>
      <option value="original">Original — no compression</option>
    </select>
    <p className="text-xs leading-relaxed text-slate-500 dark:text-slate-400">Balanced optimizes eligible images without reducing pixel dimensions or rasterizing text. Preparation transfers the original PDF to the backend and returns a preview; it may use extra mentor data. Smaller saved notes reduce student downloads. Prepare up to 25 PDFs / 100 MB per batch.</p>
    <div className="space-y-3 max-h-96 overflow-y-auto">
      {files.map((file, i) => {
        const entry = entries[i]?.original === file ? entries[i] : null;
        const chosen = entry ? selectedNoteFile(entry) : file;
        const saved = file.size - chosen.size;
        return <article key={`${file.name}-${file.size}-${i}`} className="rounded-lg border border-slate-200 bg-white p-3 text-xs dark:border-slate-700 dark:bg-slate-800">
          <div className="flex justify-between gap-2"><strong className="break-all">{file.name}</strong><button type="button" disabled={busy} onClick={() => onRemove(i)} aria-label={`Remove ${file.name}`} className="text-red-600">Remove</button></div>
          <p className="mt-2">{size(file.size)} → {entry || quality === 'original' ? size(chosen.size) : 'Not prepared'}{saved > 0 && ` · ${(saved / file.size * 100).toFixed(1)}% smaller`}</p>
          <p className="mt-1 text-slate-500 dark:text-slate-300">{entry ? preparationMessage(entry.useOriginal && entry.status === 'compressed' ? 'original_selected' : entry.reason) : quality === 'original' ? 'Original bytes will be uploaded.' : 'Prepare to compare sizes and preview.'}</p>
          <div className="mt-2 flex flex-wrap gap-3"><PdfLink file={file} label="View original" />{entry?.status === 'compressed' && <PdfLink file={entry.file} label="Preview optimized PDF" />}</div>
          {entry?.status === 'compressed' && <label className="mt-3 flex items-center gap-2"><input type="checkbox" checked={entry.useOriginal} disabled={busy} onChange={() => onToggle(i)} />Use original for this file</label>}
        </article>;
      })}
    </div>
    {quality === 'balanced' && files.length > 0 && <button type="button" disabled={busy} onClick={onPrepare} className="w-full rounded-lg border border-blue-300 p-2 text-sm font-semibold text-blue-700 disabled:opacity-50 dark:text-blue-300">{progress ? `Preparing ${progress.index} of ${progress.total}…` : ready ? 'Prepare again' : 'Prepare PDFs — no publishing yet'}</button>}
    <p role="status" aria-live="polite" className="text-xs text-slate-600 dark:text-slate-300">{progress ? 'Processing. Original files remain available.' : ready ? 'Ready. Review previews, then choose Upload below.' : quality === 'balanced' && files.length ? 'Upload unlocks after preparation. You can also choose Original quality.' : ''}</p>
  </section>;
}
