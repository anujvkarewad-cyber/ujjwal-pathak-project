// Mentor sign-in — full page. Credentials are configured on the backend
// (MENTOR_ACCOUNTS / MENTOR_EMAIL+MENTOR_PASSWORD_HASH). On success the JWT is
// stored for all dashboard API calls and the user lands on the dashboard.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, LogIn, Mail, ShieldCheck } from 'lucide-react';
import { loginMentor } from '@/api/content';
import { setToken } from '@/api/backendClient';

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const res = await loginMentor(email.trim(), password);
      setToken(res.token);
      try { localStorage.setItem('upm_mentor_email', res.email || email.trim()); } catch { /* ignore */ }
      navigate('/', { replace: true });
      window.dispatchEvent(new CustomEvent('upm:auth-ok'));
    } catch (err) {
      setError(err?.status === 401 ? 'Invalid email or password.' : (err.message || 'Could not sign in. Check that the backend is running.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 relative overflow-hidden p-4">
      {/* Background accents */}
      <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-blue-200/40 dark:bg-blue-500/10 blur-3xl" aria-hidden="true" />
      <div className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full bg-violet-200/40 dark:bg-violet-500/10 blur-3xl" aria-hidden="true" />

      <div className="w-full max-w-md relative">
        {/* Brand */}
        <div className="flex items-center gap-3 justify-center mb-6">
          <div className="w-12 h-12 rounded-2xl bg-[#2563EB] text-white flex items-center justify-center font-bold text-lg shadow-lg shadow-blue-600/30">UP</div>
          <div>
            <div className="font-heading font-bold text-slate-900 dark:text-white leading-tight">UJJWAL PATHAK</div>
            <div className="text-[11px] tracking-[0.22em] font-semibold text-slate-500 dark:text-slate-400">MENTORSHIP PROGRAM</div>
          </div>
        </div>

        {/* Card */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xl shadow-slate-200/60 dark:shadow-none p-8">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck className="w-5 h-5 text-[#2563EB]" />
            <h1 className="font-heading text-xl font-bold text-slate-900 dark:text-white">Mentor Dashboard</h1>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">Sign in with your mentor ID to access students, tests, messages, analytics and reports.</p>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Mentor ID (email)</label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="mentor@ujjwalpathak.in"
                  autoComplete="username"
                  autoFocus
                  className="w-full h-11 pl-10 pr-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/50"
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Password</label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className="w-full h-11 pl-10 pr-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-sm text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#2563EB]/50"
                />
              </div>
            </div>

            {error ? (
              <div className="text-sm text-rose-600 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-900/50 rounded-lg px-3 py-2" data-testid="login-error">{error}</div>
            ) : null}

            <button
              type="submit"
              disabled={busy || !email || !password}
              className="w-full h-11 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] disabled:opacity-50 text-white text-sm font-bold inline-flex items-center justify-center gap-2 transition-colors"
              data-testid="login-submit"
            >
              <LogIn className="w-4 h-4" /> {busy ? 'Signing in…' : 'Sign in to Dashboard'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-400 mt-4">Authorized mentorship team only · every access is audit-logged</p>
      </div>
    </div>
  );
}
