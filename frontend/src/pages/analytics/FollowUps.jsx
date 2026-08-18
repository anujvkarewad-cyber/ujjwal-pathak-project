// Analytics → Follow-up Actions. Mentor interventions with status and notes.
import { useState } from 'react';
import { CheckCircle2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { useCreateFollowup, useFollowups, useUpdateFollowup } from '@/api/hooks-content';
import { Skeleton } from '@/components/common/Skeleton';
import InlineError from '@/components/common/InlineError';
import { Button } from '@/components/ui/button';
import { cn } from '@/utils/format';

export default function FollowUps() {
  const { data, isLoading, isError, error } = useFollowups();
  const create = useCreateFollowup();
  const update = useUpdateFollowup();
  const [title, setTitle] = useState('');
  const [studentId, setStudentId] = useState('');
  const [priority, setPriority] = useState('medium');

  const items = data?.items || [];

  const submit = (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    create.mutate(
      { studentId: studentId || null, title: title.trim(), priority },
      {
        onSuccess: () => {
          setTitle('');
          setStudentId('');
          toast.success('Follow-up created');
        },
        onError: (err) => toast.error(err.message),
      }
    );
  };

  return (
    <div className="space-y-4" data-testid="followups">
      <div>
        <h2 className="font-heading text-xl font-semibold text-slate-900 dark:text-white">Follow-up Actions</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Track mentor interventions for weak, at-risk and declining students.</p>
      </div>

      <form onSubmit={submit} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 flex flex-wrap items-center gap-2">
        <input
          className="flex-1 min-w-[200px] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-sm"
          placeholder="Action title (e.g. Call student, assign chapter revision)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          className="w-40 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-1.5 text-sm"
          placeholder="studentId (optional)"
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
        />
        <select className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1.5 text-sm" value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
        <Button size="sm" type="submit" disabled={!title.trim() || create.isPending}>
          <Plus className="w-3.5 h-3.5 mr-1" /> Add
        </Button>
      </form>

      <div className="space-y-2">
        {isLoading && <Skeleton className="h-32 w-full" />}
        {!isLoading && isError && <InlineError error={error} title="Couldn’t load follow-ups" />}
        {!isLoading && !isError && items.map((f) => (
          <div key={f.followupId} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-medium text-slate-800 dark:text-slate-100">{f.title}</span>
              {f.studentId && <span className="font-mono text-xs text-slate-500">{f.studentId}</span>}
              <span className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-semibold border',
                f.priority === 'high' ? 'bg-rose-50 text-rose-700 border-rose-200' :
                f.priority === 'medium' ? 'bg-amber-50 text-amber-700 border-amber-200' :
                'bg-slate-50 text-slate-600 border-slate-200'
              )}>
                {f.priority}
              </span>
              <span className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-semibold border',
                f.status === 'completed' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'
              )}>
                {f.status}
              </span>
              <span className="ml-auto flex items-center gap-2">
                {f.status !== 'completed' && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-emerald-600 border-emerald-200 hover:bg-emerald-50"
                    onClick={() => update.mutate({ id: f.followupId, body: { status: 'completed' } }, { onSuccess: () => toast.success('Marked completed') })}
                  >
                    <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Complete
                  </Button>
                )}
              </span>
            </div>
            {(f.notes || []).length > 0 && (
              <div className="mt-2 space-y-1">
                {(f.notes || []).map((n, i) => (
                  <p key={i} className="text-xs text-slate-500">“{n.note}” — {n.by}, {new Date(n.at).toLocaleString()}</p>
                ))}
              </div>
            )}
          </div>
        ))}
        {!isLoading && !isError && items.length === 0 && <p className="text-sm text-slate-500 p-6 text-center">No follow-up actions yet.</p>}
      </div>
    </div>
  );
}
