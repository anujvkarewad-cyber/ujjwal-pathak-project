import { useState } from 'react';
import { Pin, Send, Users, Calendar, Trash2 } from 'lucide-react';
import { useAnnouncements, useCreateAnnouncement, useTogglePinAnnouncement, useDeleteAnnouncement } from '@/api/hooks';
import { sendWhatsAppAnnouncement } from '@/api/messages';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogFooter, AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel } from '@/components/ui/alert-dialog';
import { ALL_BATCHES, ENROLLMENT_BATCHES } from '@/constants/batches';

export default function Announcements() {
  const { data: list = [], isLoading, error: loadError } = useAnnouncements();
  const createMut = useCreateAnnouncement();
  const pinMut = useTogglePinAnnouncement();
  const deleteMut = useDeleteAnnouncement();
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleteNotice, setDeleteNotice] = useState('');

  const requestDelete = (announcement) => {
    setDeleteError('');
    setDeleteNotice('');
    setDeleteTarget(announcement);
  };
  const confirmDelete = async (event) => {
    event.preventDefault();
    if (!deleteTarget || deleteMut.isPending) return;
    setDeleteError('');
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
      setDeleteNotice('Announcement deleted. Students will no longer see it after refreshing the app.');
    } catch (err) {
      setDeleteError(err.message || 'Could not delete the announcement. Please try again.');
    }
  };

  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState(ALL_BATCHES);
  const [waAlso, setWaAlso] = useState(true);
  const [waStatus, setWaStatus] = useState('');

  const create = (e) => {
    e.preventDefault();
    if (!title.trim() || !body.trim()) return;
    const waText = `${title.trim()}: ${body.trim()}`;
    createMut.mutate(
      { title: title.trim(), body: body.trim(), audience },
      {
        onSuccess: async () => {
          setTitle(''); setBody(''); setAudience(ALL_BATCHES);
          if (waAlso) {
            setWaStatus('Sending on WhatsApp…');
            try {
              const r = await sendWhatsAppAnnouncement(waText);
              setWaStatus(`WhatsApp: delivered to ${r.sent} student${r.sent === 1 ? '' : 's'} (${r.skippedNoNumber} without a saved number).`);
            } catch {
              setWaStatus('WhatsApp send failed — announcement still published in app.');
            }
          }
        },
      }
    );
  };

  const pinned = list.filter(a => a.pinned);
  const rest = list.filter(a => !a.pinned);

  return (
    <div className="space-y-6" data-testid="announcements-page">
      {loadError && <p role="alert" className="text-sm text-red-600">{loadError.message || 'Could not load announcements.'}</p>}
      {deleteNotice && <p role="status" className="text-sm text-emerald-700">{deleteNotice}</p>}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => { if (!open && !deleteMut.isPending) setDeleteTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete announcement?</AlertDialogTitle>
            <AlertDialogDescription>
              Delete “{deleteTarget?.title}” from the dashboard and student announcement list? Sheet sync will not restore it. Already delivered notifications cannot be recalled.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && <p role="alert" className="text-sm text-red-600">{deleteError}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMut.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete} disabled={deleteMut.isPending} className="bg-red-600 hover:bg-red-700" data-testid="confirm-delete-announcement">
              {deleteMut.isPending ? 'Deleting...' : 'Delete announcement'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <form onSubmit={create} className="lg:col-span-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 space-y-3" data-testid="create-announcement">
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white">Create Announcement</h3>
          <input
            data-testid="announcement-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200"
          />
          <textarea
            data-testid="announcement-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Write your announcement..."
            rows={5}
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200 resize-none"
          />
          <select
            data-testid="announcement-audience"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            className="w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm text-slate-700 dark:text-slate-200 outline-none focus:border-[#2563EB]"
          >
            {[ALL_BATCHES, ...ENROLLMENT_BATCHES].map(o => <option key={o}>{o}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200 select-none">
            <input
              type="checkbox"
              checked={waAlso}
              onChange={(e) => setWaAlso(e.target.checked)}
              data-testid="announcement-whatsapp"
              className="w-4 h-4 rounded border-slate-300 accent-[#2563EB]"
            />
            Also send on WhatsApp to students with a saved number
          </label>
          {waStatus && <p className="text-xs text-emerald-600 dark:text-emerald-400" data-testid="whatsapp-status">{waStatus}</p>}
          <button
            type="submit"
            disabled={createMut.isPending}
            data-testid="publish-announcement"
            className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-60"
          >
            <Send className="w-4 h-4" /> {createMut.isPending ? 'Publishing...' : 'Publish'}
          </button>
        </form>

        <div className="lg:col-span-2 space-y-4">
          {isLoading && <Skeleton className="h-32 w-full" />}
          {pinned.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 mb-2 flex items-center gap-1.5">
                <Pin className="w-3 h-3" /> Pinned
              </div>
              <div className="space-y-3">
                {pinned.map(a => <Card key={a.id} a={a} onPin={() => pinMut.mutate(a.id)} onDelete={() => requestDelete(a)} deleting={deleteMut.isPending} pinned />)}
              </div>
            </div>
          )}
          {rest.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 mb-2">History</div>
              <div className="space-y-3">
                {rest.map(a => <Card key={a.id} a={a} onPin={() => pinMut.mutate(a.id)} onDelete={() => requestDelete(a)} deleting={deleteMut.isPending} />)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Card({ a, onPin, onDelete, deleting, pinned }) {
  return (
    <div className={cn(
      'border rounded-xl p-5 transition-colors',
      pinned
        ? 'bg-blue-50/60 dark:bg-blue-500/5 border-blue-200 dark:border-blue-500/20'
        : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
    )} data-testid={`ann-${a.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h4 className="font-heading font-semibold text-slate-900 dark:text-white">{a.title}</h4>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1"><Users className="w-3 h-3" />{a.audience}</span>
            <span className="inline-flex items-center gap-1"><Calendar className="w-3 h-3" />{a.date}</span>
            <span>· by {a.author}</span>
          </div>
        </div>
        <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting || !a.id}
          data-testid={`delete-${a.id}`}
          aria-label={`Delete announcement: ${a.title}`}
          className="inline-flex items-center gap-1.5 px-2 py-2 rounded-lg text-sm font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-50"
        >
          <Trash2 className="w-4 h-4" /> Delete
        </button>
        <button
          type="button"
          disabled={deleting}
          onClick={onPin}
          data-testid={`pin-${a.id}`}
          className={cn('p-2 rounded-lg transition-colors', pinned ? 'text-[#2563EB] bg-blue-100 dark:bg-blue-500/20' : 'text-slate-400 hover:text-[#2563EB] hover:bg-slate-100 dark:hover:bg-slate-800')}
          aria-label="Toggle pin"
        >
          <Pin className="w-4 h-4" />
        </button>
        </div>
      </div>
      <p className="mt-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{a.body}</p>
    </div>
  );
}
