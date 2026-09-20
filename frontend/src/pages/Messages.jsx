// Messages — mentor inbox for student app messages. Left: all student threads
// with unread badges; right: the conversation + reply box. Replies appear in
// the student app's Messenger instantly on its next poll.
import { useCallback, useEffect, useRef, useState } from 'react';
import { MessageCircle, Send, Smartphone } from 'lucide-react';
import { fetchInbox, fetchThread, replyToStudent, fetchWhatsAppStatus, fetchWhatsAppLog } from '@/api/messages';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const fmtTime = (iso) => {
  try {
    const d = new Date(iso);
    const today = new Date().toDateString() === d.toDateString();
    return today
      ? d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
};

export default function Messages() {
  const [threads, setThreads] = useState(null);
  const [selected, setSelected] = useState(null); // studentId
  const [thread, setThread] = useState(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [waStatus, setWaStatus] = useState(null);
  const [waLog, setWaLog] = useState([]);
  const bottomRef = useRef(null);

  const loadInbox = useCallback(() => {
    fetchInbox()
      .then((res) => setThreads(res?.threads || []))
      .catch((e) => setError(e?.message || 'Could not load messages'));
    fetchWhatsAppStatus().then(setWaStatus).catch(() => setWaStatus(null));
    fetchWhatsAppLog().then((res) => setWaLog(res?.entries || [])).catch(() => setWaLog([]));
  }, []);

  useEffect(() => { loadInbox(); const t = setInterval(loadInbox, 20000); return () => clearInterval(t); }, [loadInbox]);

  useEffect(() => {
    if (!selected) { setThread(null); return; }
    let alive = true;
    fetchThread(selected)
      .then((res) => { if (alive) setThread(res); })
      .catch((e) => { if (alive) setError(e?.message || 'Could not open thread'); });
    return () => { alive = false; };
  }, [selected]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [thread?.messages?.length]);

  const openThread = (studentId) => {
    setSelected(studentId);
    setThreads((prev) => (prev || []).map((t) => (t.studentId === studentId ? { ...t, unreadForMentor: 0 } : t)));
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected || sending) return;
    setSending(true);
    try {
      const res = await replyToStudent(selected, text);
      setThread((prev) => prev && { ...prev, messages: [...(prev.messages || []), res.message] });
      setDraft('');
      loadInbox();
    } catch (e) {
      setError(e?.message || 'Could not send reply');
    } finally {
      setSending(false);
    }
  };

  const totalUnread = (threads || []).reduce((a, t) => a + (t.unreadForMentor || 0), 0);
  const active = (threads || []).find((t) => t.studentId === selected);

  const waActive = waStatus?.active;
  const waEntries = waLog.filter((e) => e.purpose === 'student_message');

  return (
    <div className="space-y-4" data-testid="messages-page">
      {/* WhatsApp dual-delivery bar */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Smartphone className={cn('w-4 h-4', waActive ? 'text-emerald-500' : 'text-slate-400')} />
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">WhatsApp delivery</span>
          <span className={cn('px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide', waActive ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400')}>
            {waActive ? `Active · ${waStatus.provider}` : 'Not configured'}
          </span>
        </div>
        <span className="text-xs text-slate-500">
          {waActive
            ? 'Every student message lands here in the dashboard AND on your WhatsApp.'
            : 'Messages arrive in the dashboard now; add WhatsApp provider credentials on the backend to mirror them to your WhatsApp.'}
        </span>
        {waEntries.length > 0 ? (
          <span className="ml-auto text-[11px] text-slate-400">
            Last mirrored: {fmtTime(waEntries[0].at)} · {waEntries.length} shown
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-4 h-[calc(100vh-230px)] min-h-[420px]">
      {/* Thread list */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center gap-2">
          <MessageCircle className="w-4 h-4 text-[#2563EB]" />
          <span className="font-heading font-semibold text-slate-900 dark:text-white text-sm">Student messages</span>
          {totalUnread > 0 ? (
            <span className="ml-auto px-2 py-0.5 rounded-full bg-rose-500 text-white text-[11px] font-bold">{totalUnread} new</span>
          ) : null}
        </div>
        <div className="flex-1 overflow-y-auto">
          {threads === null && <div className="p-3 space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div>}
          {threads !== null && threads.length === 0 && (
            <p className="text-sm text-slate-500 text-center px-4 py-8">No messages yet. When students write to you in the app, their messages appear here.</p>
          )}
          {(threads || []).map((t) => (
            <button
              key={t.studentId}
              onClick={() => openThread(t.studentId)}
              className={cn(
                'w-full text-left px-4 py-3 border-b border-slate-100 dark:border-slate-800/60 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors',
                selected === t.studentId && 'bg-blue-50/60 dark:bg-blue-500/10',
              )}
            >
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-[#2563EB] text-white flex items-center justify-center text-xs font-bold shrink-0">
                  {(t.studentName || t.studentId).split(' ').map((x) => x[0]).join('').slice(0, 2).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{t.studentName || t.studentId}</span>
                    {t.unreadForMentor > 0 ? (
                      <span className="px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-bold shrink-0">{t.unreadForMentor}</span>
                    ) : null}
                    <span className="ml-auto text-[10px] text-slate-400 shrink-0">{fmtTime(t.lastMessage?.at)}</span>
                  </div>
                  <div className="text-xs text-slate-500 truncate">{t.lastMessage ? `${t.lastMessage.from === 'mentor' ? 'You: ' : ''}${t.lastMessage.text}` : t.batch || t.studentId}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Conversation */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden flex flex-col">
        {!selected ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 gap-2">
            <MessageCircle className="w-8 h-8 text-slate-300" />
            <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">Select a student to read and reply</p>
            <p className="text-xs text-slate-400 max-w-xs">Replies reach the student's app Messenger. New student messages also ping your WhatsApp when it is configured.</p>
          </div>
        ) : (
          <>
            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800">
              <div className="font-semibold text-slate-900 dark:text-white text-sm">{active?.studentName || selected}</div>
              <div className="text-xs text-slate-400">{selected}{active?.batch ? ` · ${active.batch}` : ''}</div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2.5 bg-slate-50/60 dark:bg-slate-950/40">
              {!thread && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12 w-2/3" />)}
              {(thread?.messages || []).map((m) => (
                <div key={m.id} className={cn('max-w-[75%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed', m.from === 'mentor' ? 'ml-auto bg-[#2563EB] text-white rounded-br-sm' : 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 rounded-bl-sm')}>
                  {m.text}
                  <div className={cn('text-[10px] mt-1', m.from === 'mentor' ? 'text-blue-100' : 'text-slate-400')}>{fmtTime(m.at)}</div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
            <div className="p-3 border-t border-slate-200 dark:border-slate-800 flex items-end gap-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={`Reply to ${active?.studentName || selected}… (Enter to send)`}
                rows={2}
                className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40 resize-none"
              />
              <button
                onClick={send}
                disabled={!draft.trim() || sending}
                className="h-10 px-4 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] disabled:opacity-40 text-white text-sm font-semibold inline-flex items-center gap-2"
              >
                <Send className="w-4 h-4" /> Send
              </button>
            </div>
          </>
        )}
      </div>
        {error ? <div className="lg:col-span-2 text-xs text-rose-600">{error}</div> : null}
      </div>

      {/* WhatsApp mirror log */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Smartphone className="w-4 h-4 text-[#25D366]" />
          <h3 className="font-heading font-semibold text-slate-900 dark:text-white text-sm">Mirrored to WhatsApp</h3>
          <span className="ml-auto text-[11px] text-slate-400">student messages forwarded to the mentor number</span>
        </div>
        {waEntries.length === 0 ? (
          <p className="text-xs text-slate-400">No WhatsApp deliveries yet — they appear here the moment a student messages you.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {waEntries.map((e, i) => (
              <div key={i} className="flex items-center gap-2.5 border border-slate-100 dark:border-slate-800 rounded-lg px-3 py-2">
                <span className={cn('w-2 h-2 rounded-full shrink-0', e.status === 'sent' ? 'bg-emerald-500' : 'bg-amber-500')} />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">→ +{e.to} · {e.detail}</div>
                  <div className="text-[10px] text-slate-400">{fmtTime(e.at)} · {e.status}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
