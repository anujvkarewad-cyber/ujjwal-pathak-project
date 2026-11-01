// Password Reset — mentor-side reset of a student's login, mirrored into the Students sheet.
//
// Why this screen exists: a student who is told "Incorrect password" cannot fix it
// themselves, and the sheet cell that the welcome mail is built from goes stale on its
// own. So the queue here is the two things the mentor would otherwise have to assemble by
// hand — who is being refused right now, and whose sheet value would not work — and the
// action sets both places in one click. The new password is shown once and never sent
// anywhere by the app: no push, no mail, no schedule. The mentor passes it on.
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle, Check, Copy, Eye, EyeOff, KeyRound, Loader2, RefreshCw,
  Search, ShieldAlert, Wand2,
} from 'lucide-react';
import {
  fetchPasswordHistory, fetchPasswordQueue, searchPasswordStudents,
  setStudentPassword, syncPasswordToSheet,
} from '@/api/passwords';
import { cn } from '@/utils/format';

const fmtWhen = (iso) => {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch {
    return String(iso).slice(0, 16);
  }
};

const STATE_CHIP = {
  stale: ['sheet has a dead password', 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'],
  blank: ['no password in the sheet', 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'],
  marked: ['sheet holds a note, not a password', 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'],
  noRow: ['not in the Students sheet', 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'],
  ok: ['sheet matches', 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'],
};

// shown as the Students sheet spells it - "Both" is a group of its own here
const groupLabel = (r) => (r?.groupText || (r?.groups || []).filter(Boolean).join(' + ')).trim();

function Chip({ tone = 'slate', children }) {
  return (
    <span className={cn(
      'px-2 py-0.5 rounded-full text-[11px] font-semibold',
      tone === 'rose' && 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
      tone === 'amber' && 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
      tone === 'blue' && 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
      tone === 'emerald' && 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
      tone === 'slate' && 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    )}
    >
      {children}
    </span>
  );
}

/** The action itself: type a password or let it be generated, then show it once. */
function ResetPanel({ row, onDone }) {
  const [pwd, setPwd] = useState('');
  const [note, setNote] = useState('');
  const [forceChange, setForceChange] = useState(true);
  const [reveal, setReveal] = useState(true);
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState(null);
  const qc = useQueryClient();

  const reset = useMutation({
    mutationFn: () => setStudentPassword({
      studentId: row.studentId,
      password: pwd.trim(),
      note: note.trim(),
      forceChange,
    }),
    onSuccess: (res) => {
      setResult(res);
      qc.invalidateQueries({ queryKey: ['password-queue'] });
    },
  });
  const retrySheet = useMutation({
    mutationFn: () => syncPasswordToSheet(row.studentId, result?.password || pwd.trim()),
    onSuccess: (res) => {
      setResult((r) => ({ ...(r || {}), sheetWritten: !!res?.sheetWritten || !!res?.ok }));
      qc.invalidateQueries({ queryKey: ['password-queue'] });
    },
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(result?.password || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  };

  if (result?.password) {
    return (
      <div className="mt-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 px-3 py-2.5" data-testid={`pw-result-${row.studentId}`}>
        <div className="text-[11px] uppercase tracking-wide font-semibold text-slate-500">
          {row.studentName || row.studentId} can now sign in with
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <code className="px-2.5 py-1.5 rounded-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 font-mono text-base font-bold tracking-wide select-all">
            {result.password}
          </code>
          <button type="button" onClick={copy} data-testid="pw-copy"
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-[#2563EB] text-white hover:bg-[#1d4ed8]">
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" onClick={onDone} className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
            Done — hide it
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
          {result.sheetWritten
            ? <Chip tone="emerald">Students sheet updated</Chip>
            : <Chip tone="rose">sheet NOT updated</Chip>}
          {result.generated ? <Chip tone="slate">generated</Chip> : null}
          {result.forceChange ? <Chip tone="blue">asked to set their own on next login</Chip> : null}
          {!result.sheetWritten ? (
            <button type="button" data-testid="pw-sheet-retry" disabled={retrySheet.isPending}
              onClick={() => retrySheet.mutate()}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-semibold border border-slate-200 dark:border-slate-800 hover:border-[#2563EB] disabled:opacity-60">
              <RefreshCw className={cn('w-3 h-3', retrySheet.isPending && 'animate-spin')} /> Update the sheet cell
            </button>
          ) : null}
        </div>
        <div className="mt-1.5 text-[11px] text-slate-500 leading-snug">
          {result.sheetWritten
            ? 'Shown once here — not stored, not logged, not pushed. Send it yourself, and the sheet already holds the same value.'
            : `${result.message || 'The app password works but the sheet was not written.'} Until it is, do not rely on the sheet cell for this student.`}
        </div>
      </div>
    );
  }

  const tooShort = pwd.trim().length > 0 && pwd.trim().length < 6;
  return (
    <div className="mt-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[190px]">
          <input
            type={reveal ? 'text' : 'password'}
            value={pwd}
            onChange={(e) => setPwd(e.target.value)}
            placeholder="Type a password — leave blank to generate one"
            autoComplete="off"
            spellCheck={false}
            data-testid="pw-input"
            className="w-full px-3 py-1.5 pr-9 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
          />
          <button type="button" onClick={() => setReveal((v) => !v)} aria-label="Show or hide the password"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
            {reveal ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why (optional — kept in the log, not shown to the student)"
          data-testid="pw-note"
          className="flex-1 min-w-[170px] px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
        />
        <button type="button" onClick={() => setPwd('')} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-800 hover:border-[#2563EB]">
          <Wand2 className="w-3.5 h-3.5" /> Generate
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-500">
          <input type="checkbox" checked={forceChange} onChange={(e) => setForceChange(e.target.checked)} data-testid="pw-force" className="rounded border-slate-300" />
          Ask them to set their own password on next login
        </label>
        {tooShort ? <span className="text-[11px] font-semibold text-rose-600">at least 6 characters</span> : null}
        <button type="button" data-testid={`pw-submit-${row.studentId}`}
          disabled={tooShort || reset.isPending || !row.hasAccount}
          onClick={() => reset.mutate()}
          className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#2563EB] text-white hover:bg-[#1d4ed8] disabled:opacity-60">
          {reset.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />}
          {reset.isPending ? 'Setting…' : `Reset ${row.studentId}`}
        </button>
      </div>
      {reset.isError ? (
        <div className="mt-2 text-[11px] font-semibold text-rose-600" data-testid="pw-error">
          {reset.error?.message || 'Could not reset this password.'}
        </div>
      ) : null}
      {!row.hasAccount ? (
        <div className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
          No app account for this ID yet — add the login first (Students → import from sheet), then reset.
        </div>
      ) : null}
    </div>
  );
}

function StudentRow({ row, defaultOpen }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const chip = STATE_CHIP[row.sheetState] || STATE_CHIP.ok;
  return (
    <div className="border border-slate-200 dark:border-slate-800 rounded-xl bg-white dark:bg-slate-900 px-3.5 py-2.5" data-testid={`pw-row-${row.studentId}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-800 dark:text-slate-100">{row.studentName || row.studentId}</span>
            <span className="text-[11px] font-mono text-slate-400">{row.studentId}</span>
            {row.openFails ? <Chip tone="rose">refused {row.openFails}× login{row.openFails > 1 ? 's' : ''}</Chip> : null}
            <Chip tone={row.sheetState === 'stale' ? 'rose' : (row.sheetState === 'blank' ? 'amber' : 'slate')}>{chip[0]}</Chip>
            {row.accessEnabled === false ? <Chip tone="slate">app access off</Chip> : null}
            {row.forcePasswordChange ? <Chip tone="blue">will be asked to change it</Chip> : null}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400 truncate">
            {[row.batch, groupLabel(row) || 'no group set'].filter(Boolean).join(' · ')}
            {row.lastFailAt ? ` · refused ${fmtWhen(row.lastFailAt)}` : ''}
            {row.lastLoginAt ? ` · last in ${fmtWhen(row.lastLoginAt)}` : ''}
            {row.scopeFrom === 'accounts' ? ' · sheet did not list this student' : ''}
          </div>
        </div>
        <button type="button" data-testid={`pw-set-${row.studentId}`} onClick={() => setOpen((v) => !v)}
          className="shrink-0 px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-800 hover:border-[#2563EB] hover:text-[#2563EB]">
          {open ? 'Close' : 'Set password'}
        </button>
      </div>
      {open ? <ResetPanel row={row} onDone={() => { setOpen(false); }} /> : null}
    </div>
  );
}

const MODES = [
  { key: 'queue', label: 'Needs a reset' },
  { key: 'find', label: 'Find a student' },
  { key: 'history', label: 'History' },
];

export default function PasswordReset({ scopedStudentIds } = {}) {
  const [days, setDays] = useState(7);
  const [mode, setMode] = useState('queue');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const qc = useQueryClient();

  const queue = useQuery({
    queryKey: ['password-queue', days],
    queryFn: () => fetchPasswordQueue(days),
    staleTime: 30_000,
    retry: 1,
  });
  const found = useQuery({
    queryKey: ['password-search', search],
    queryFn: () => searchPasswordStudents(search),
    enabled: search.trim().length >= 2,
  });
  const history = useQuery({
    queryKey: ['password-history'],
    queryFn: () => fetchPasswordHistory(40),
    enabled: mode === 'history',
  });

  const rows = useMemo(() => {
    const source = mode === 'find' ? (search.trim().length >= 2 ? (found.data?.rows || []) : []) : queue.data?.rows || [];
    return source.filter(r => !scopedStudentIds || scopedStudentIds.includes(r.studentId));
  }, [mode, found.data, queue.data, search, scopedStudentIds]);

  const counts = queue.data?.counts || {};
  const meter = queue.data?.meter || {};

  return (
    <div className="space-y-3" data-testid="password-reset-page">
      {scopedStudentIds && <p className="text-xs text-slate-500">Queue, search and history are scoped to this workspace. Summary counters below are global password-audit totals.</p>}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3">
        <div className="flex flex-wrap items-start gap-3">
          <span className="mt-0.5 h-8 w-8 shrink-0 rounded-lg bg-slate-100 dark:bg-slate-800 grid place-items-center">
            <KeyRound className="h-4 w-4 text-slate-600 dark:text-slate-300" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold text-slate-800 dark:text-slate-100">Password reset</h2>
            <p className="text-[11px] text-slate-500 leading-snug">
              Students who are being refused at login, plus every sheet cell that would not work. Setting a password here
              updates the app account and the Students sheet together — the value is shown once, on this screen, and nothing is
              sent to the student by the app.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              data-testid="pw-days"
              className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs"
              aria-label="How far back to look for failed logins"
            >
              {[3, 7, 14, 30].map((d) => <option key={d} value={d}>last {d} days</option>)}
            </select>
            <button type="button" data-testid="pw-refresh"
              onClick={() => { qc.invalidateQueries({ queryKey: ['password-queue'] }); queue.refetch(); }}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-800 hover:border-[#2563EB]">
              <RefreshCw className={cn('w-3 h-3', queue.isFetching && 'animate-spin')} /> Refresh
            </button>
          </div>
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <Chip tone={counts.failingNow ? 'rose' : 'emerald'}>
            {counts.failingNow ? `${counts.failingNow} stuck at login` : 'nobody stuck at login'}
          </Chip>
          <Chip tone={meter.total ? 'emerald' : 'slate'}>
            sheet usable {meter.valid || 0}/{meter.total || 0}{queue.data?.usablePct != null ? ` (${queue.data.usablePct}%)` : ''}
          </Chip>
          {counts.stale ? <Chip tone="rose">{counts.stale} dead value in the sheet</Chip> : null}
          {counts.blank ? <Chip tone="amber">{counts.blank} blank in the sheet</Chip> : null}
          {counts.marked ? <Chip tone="slate">{counts.marked} holding a note</Chip> : null}
          {counts.noAccount ? <Chip tone="slate">{counts.noAccount} with no app account</Chip> : null}
        </div>
        {queue.data && queue.data.sheetOk === false ? (
          <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50/70 dark:bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
            <AlertTriangle className="w-3.5 h-3.5 mt-px shrink-0" />
            <span>{queue.data.sheetNote || 'The Students sheet could not be read, so sheet states below are unknown rather than clean. The app still gets the password; the sheet can be updated with the retry button.'}</span>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {MODES.map((m) => (
          <button key={m.key} type="button" onClick={() => setMode(m.key)} data-testid={`pw-tab-${m.key}`}
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors',
              mode === m.key
                ? 'bg-[#2563EB] text-white border-[#2563EB]'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-800 hover:border-[#2563EB]',
            )}
          >
            {m.label}
            {m.key === 'queue' && counts.listed ? ` · ${counts.listed}` : ''}
          </button>
        ))}
        {mode === 'find' ? (
          <div className="relative ml-auto">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') setSearch(query.trim()); }}
              onBlur={() => setSearch(query.trim())}
              placeholder="Student ID or name, then Enter"
              data-testid="pw-search"
              className="pl-9 pr-3 py-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/40"
            />
          </div>
        ) : null}
      </div>

      {mode === 'history' ? (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          {(history.data?.entries || []).filter(e => !scopedStudentIds || scopedStudentIds.includes(e.detail?.studentId)).length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">No password resets from this screen yet.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="text-left font-semibold px-3 py-2">When</th>
                  <th className="text-left font-semibold px-3 py-2">Student</th>
                  <th className="text-left font-semibold px-3 py-2">How</th>
                  <th className="text-left font-semibold px-3 py-2">Sheet</th>
                  <th className="text-left font-semibold px-3 py-2">Note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {(history.data?.entries || []).filter(e => !scopedStudentIds || scopedStudentIds.includes(e.detail?.studentId)).map((e, i) => (
                  <tr key={`${e.at}-${i}`} className="text-xs">
                    <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtWhen(e.at)}</td>
                    <td className="px-3 py-2 font-mono text-slate-600 dark:text-slate-300">{e.detail?.studentId}</td>
                    <td className="px-3 py-2 text-slate-500">
                      {e.action === 'password_reset_sheet_sync' ? 'sheet cell only' : (e.detail?.generated ? 'generated' : 'mentor typed')}
                      {e.detail?.forceChange ? ' · must change on next login' : ''}
                    </td>
                    <td className="px-3 py-2">
                      {e.detail?.sheetWritten ? <Chip tone="emerald">written</Chip> : <Chip tone="rose">failed</Chip>}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{e.detail?.note || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="px-3 py-2 text-[11px] text-slate-400 border-t border-slate-100 dark:border-slate-800/60">
            Passwords are never written to this log — only who, when and whether the sheet followed.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {queue.isLoading ? (
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-8 text-center text-sm text-slate-500">
              Reading the Students sheet and the login log…
            </div>
          ) : queue.isError ? (
            <div className="rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50/70 dark:bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
              Could not load this list ({queue.error?.message || 'unknown error'}).
            </div>
          ) : mode === 'find' && search.trim().length < 2 ? (
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-8 text-center text-sm text-slate-500">
              Type a student ID (e.g. UMP0132) or their name to set a password for someone who is not on the list.
            </div>
          ) : rows.length === 0 ? (
            <div className="rounded-xl border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50/60 dark:bg-emerald-500/10 px-4 py-8 text-center text-sm text-emerald-700 dark:text-emerald-300">
              <ShieldAlert className="w-4 h-4 mx-auto mb-1.5 opacity-70" />
              Nothing to fix — no refused logins in this window and no sheet cell that would fail.
            </div>
          ) : (
            rows.map((r) => <StudentRow key={r.studentId} row={r} />)
          )}
        </div>
      )}
    </div>
  );
}
