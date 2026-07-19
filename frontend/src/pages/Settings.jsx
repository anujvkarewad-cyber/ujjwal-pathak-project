import { useEffect, useState } from 'react';
import { Bell, Moon, Sun, Mail, MessageSquare, Save } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import {
  useMentorProfile, useUpdateMentorProfile,
  useNotificationSettings, useUpdateNotificationSettings,
} from '@/api/hooks';
import { Skeleton } from '@/components/common/Skeleton';
import { cn } from '@/utils/format';

const Toggle = ({ checked, onChange, testid }) => (
  <button
    data-testid={testid}
    onClick={onChange}
    className={cn('w-11 h-6 rounded-full transition-colors relative', checked ? 'bg-[#2563EB]' : 'bg-slate-300 dark:bg-slate-700')}
    aria-pressed={checked}
    aria-label="toggle"
  >
    <span className={cn('absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform', checked && 'translate-x-5')} />
  </button>
);

export default function Settings() {
  const { theme, toggle } = useTheme();
  const { data: mentor, isLoading: mentorLoading } = useMentorProfile();
  const { data: notifs } = useNotificationSettings();
  const updateProfile = useUpdateMentorProfile();
  const updateNotifs = useUpdateNotificationSettings();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (mentor) { setName(mentor.name); setEmail(mentor.email); }
  }, [mentor]);

  const save = (e) => {
    e.preventDefault();
    updateProfile.mutate({ name, email }, {
      onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000); },
    });
  };

  const flip = (key) => () => notifs && updateNotifs.mutate({ [key]: !notifs[key] });

  if (mentorLoading || !mentor) {
    return (
      <div className="space-y-4 max-w-4xl">
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl" data-testid="settings-page">
      <form onSubmit={save} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white text-lg">Mentor Profile</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Update your public profile details.</p>
        <div className="mt-5 flex items-center gap-4">
          <img
            src={mentor.avatar}
            alt="Mentor"
            className="w-20 h-20 rounded-2xl object-cover ring-4 ring-slate-100 dark:ring-slate-800"
          />
          <div>
            <button type="button" className="h-9 px-4 text-sm font-semibold rounded-lg border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors" data-testid="change-photo">Change Photo</button>
            <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">JPG, PNG. Max 2 MB.</p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Name</label>
            <input data-testid="settings-name" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200" />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">Email</label>
            <input data-testid="settings-email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full h-11 px-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 outline-none focus:border-[#2563EB] text-sm text-slate-800 dark:text-slate-200" />
          </div>
        </div>
        <div className="mt-5 flex items-center justify-end gap-2">
          {saved && <span className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold">Saved!</span>}
          <button type="submit" disabled={updateProfile.isPending} data-testid="save-profile" className="h-10 px-5 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-sm font-semibold inline-flex items-center gap-2 transition-colors disabled:opacity-60">
            <Save className="w-4 h-4" /> {updateProfile.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </form>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white text-lg">Appearance</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Customize how the dashboard looks.</p>
        <div className="mt-5 flex items-center justify-between p-4 rounded-lg bg-slate-50 dark:bg-slate-800/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 flex items-center justify-center">
              {theme === 'dark' ? <Moon className="w-4 h-4 text-[#2563EB]" /> : <Sun className="w-4 h-4 text-amber-500" />}
            </div>
            <div>
              <div className="font-semibold text-slate-900 dark:text-white text-sm">Dark Mode</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">Switch between light & dark themes</div>
            </div>
          </div>
          <Toggle checked={theme === 'dark'} onChange={toggle} testid="theme-toggle-settings" />
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
        <h3 className="font-heading font-semibold text-slate-900 dark:text-white text-lg">Notification Settings</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Choose what you want to be notified about.</p>
        <div className="mt-5 space-y-3">
          {[
            { icon: Mail, label: 'Email notifications', desc: 'Weekly reports & risk alerts via email', k: 'emailNotif', tid: 'notif-email' },
            { icon: MessageSquare, label: 'SMS notifications', desc: 'Urgent risk alerts via SMS', k: 'smsNotif', tid: 'notif-sms' },
            { icon: Bell, label: 'Daily digest', desc: 'A summary of yesterday, every morning', k: 'dailyDigest', tid: 'notif-daily' },
          ].map((n) => (
            <div key={n.k} className="flex items-center justify-between p-4 rounded-lg bg-slate-50 dark:bg-slate-800/40">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 flex items-center justify-center">
                  <n.icon className="w-4 h-4 text-[#2563EB]" />
                </div>
                <div>
                  <div className="font-semibold text-slate-900 dark:text-white text-sm">{n.label}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">{n.desc}</div>
                </div>
              </div>
              <Toggle checked={!!notifs?.[n.k]} onChange={flip(n.k)} testid={n.tid} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
