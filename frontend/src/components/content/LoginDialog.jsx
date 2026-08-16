// Mentor login dialog for the FastAPI backend (AI Content + Analytics).
// Appears when an API call returns 401 (upm:auth-required event) or when the
// user opens it from the Topbar lock button.
import { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { loginMentor } from '@/api/content';
import { AUTH_EVENT, getToken, setToken } from '@/api/backendClient';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

export default function LoginDialog({ open, onOpenChange }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onAuthRequired = () => onOpenChange(true);
    window.addEventListener(AUTH_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_EVENT, onAuthRequired);
  }, [onOpenChange]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const res = await loginMentor(email.trim(), password);
      setToken(res.token);
      onOpenChange(false);
      // refresh data after login
      window.dispatchEvent(new CustomEvent('upm:auth-ok'));
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-[#2563EB]" /> Mentor sign-in
          </DialogTitle>
          <DialogDescription>
            Required for AI Content review and student analytics. Credentials are configured in the backend environment.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4 py-2">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600 dark:text-slate-300">Email</label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="mentor@ujjwalpathak.in" autoFocus />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600 dark:text-slate-300">Password</label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </div>
          {error && <p className="text-sm text-rose-600" data-testid="login-error">{error}</p>}
          {getToken() && (
            <button
              type="button"
              className="text-xs text-slate-500 hover:text-slate-700"
              onClick={() => {
                setToken('');
                onOpenChange(false);
              }}
            >
              Sign out
            </button>
          )}
        </form>
        <DialogFooter>
          <Button type="submit" onClick={submit} disabled={busy || !email || !password} data-testid="login-submit">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
