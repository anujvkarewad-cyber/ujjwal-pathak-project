import { useState } from 'react';
import { Pin, Send, Users, Calendar } from 'lucide-react';
import { announcements as SEED } from '@/data/announcements';
import { cn } from '@/utils/format';

export default function Announcements() {
  const [list, setList] = useState(SEED);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState('All Batches');

  const create = (e) => {
    e.preventDefault();
    if (!title.trim() || !body.trim()) return;
    const item = {
      id: `ANN-${String(list.length + 1).padStart(3, '0')}`,
      title: title.trim(),
      body: body.trim(),
      audience,
      date: new Date().toISOString().slice(0, 10),
      pinned: false,
      author: 'Ujjwal Pathak',
    };
    setList([item, ...list]);
    setTitle(''); setBody(''); setAudience('All Batches');
  };

  const togglePin = (id) => setList(list.map(a => a.id === id ? { ...a, pinned: !a.pinned } : a));

  const pinned = list.filter(a => a.pinned);
  const rest = list.filter(a => !a.pinned);

  return (
    <div className="space-y-6" data-testid="announcements-page">
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
            {['All Batches', 'Super 30', 'Super 11', 'Last 15 Days', 'Last 40 Days'].map(o => <option key={o}>{o}</option>)}
          </select>
          <button type="submit" data-testid="publish-announcement" className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center justify-center gap-2 transition-colors">
            <Send className="w-4 h-4" /> Publish
          </button>
        </form>

        <div className="lg:col-span-2 space-y-4">
          {pinned.length > 0 && (
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 mb-2 flex items-center gap-1.5">
                <Pin className="w-3 h-3" /> Pinned
              </div>
              <div className="space-y-3">
                {pinned.map(a => <Card key={a.id} a={a} togglePin={togglePin} pinned />)}
              </div>
            </div>
          )}
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 mb-2">History</div>
            <div className="space-y-3">
              {rest.map(a => <Card key={a.id} a={a} togglePin={togglePin} />)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ a, togglePin, pinned }) {
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
        <button
          onClick={() => togglePin(a.id)}
          data-testid={`pin-${a.id}`}
          className={cn('p-2 rounded-lg transition-colors', pinned ? 'text-[#2563EB] bg-blue-100 dark:bg-blue-500/20' : 'text-slate-400 hover:text-[#2563EB] hover:bg-slate-100 dark:hover:bg-slate-800')}
          aria-label="Toggle pin"
        >
          <Pin className="w-4 h-4" />
        </button>
      </div>
      <p className="mt-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{a.body}</p>
    </div>
  );
}
