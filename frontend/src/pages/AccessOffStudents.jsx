import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Mail,
  Phone,
  MapPin,
  Clock,
  Power,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';
import { Link } from 'react-router-dom';
import { useAccessOffStudents } from '@/api/hooks';
import {
  getAdminState,
  setStudentAccess,
} from '@/api/studentAdmin';
import { cn } from '@/utils/format';

const Stat = ({ label, value, suffix, tone = 'text-slate-900 dark:text-white' }) => (
  <div className="bg-slate-50 dark:bg-slate-800/40 rounded-lg p-4">
    <div className="text-[11px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400">
      {label}
    </div>
    <div className={cn('mt-1 font-heading text-2xl font-bold', tone)}>
      {value}{suffix && <span className="text-lg text-slate-400 ml-0.5">{suffix}</span>}
    </div>
  </div>
);

export default function AccessOffStudents() {
  const { data, isLoading, isError, error, refetch } = useAccessOffStudents();
  const queryClient = useQueryClient();

  const accessMutation = useMutation({
    mutationFn: ({ id, enabled, reason }) =>
      setStudentAccess(id, enabled, reason),
    onSuccess: (_res, vars) => {
      queryClient.invalidateQueries({ queryKey: ['access-off-students'] });
      queryClient.invalidateQueries({ queryKey: ['students'] });
      queryClient.invalidateQueries({ queryKey: ['tracker'] });
      toast.success(
        vars.enabled
          ? `App access turned ON for ${vars.name}.`
          : `App access turned OFF for ${vars.name}.`,
      );
    },
    onError: (error) => toast.error(error?.message || 'Access could not be changed.'),
  });

  if (isLoading) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-xl font-bold text-slate-900 dark:text-white">
            Access OFF Students
          </h2>
          <Link to="/students" className="inline-flex items-center gap-2 text-[#2563EB] font-medium">
            <ArrowLeft className="w-4 h-4" /> Back to students
          </Link>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Stat key={i} label="Blocked Students" value="—" />
          ))}
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 h-64 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-xl font-bold text-slate-900 dark:text-white">
            Access OFF Students
          </h2>
          <Link to="/students" className="inline-flex items-center gap-2 text-[#2563EB] font-medium">
            <ArrowLeft className="w-4 h-4" /> Back to students
          </Link>
        </div>
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-10 text-center">
          <p className="text-slate-600 dark:text-slate-300">
            {error?.status === 401 ? 'Session expired. Please log in again.' : 'Unable to load blocked students.'}
          </p>
          <button
            onClick={() => refetch()}
            className="mt-4 inline-flex items-center gap-2 text-[#2563EB] font-medium"
          >
            <Clock className="w-4 h-4" /> Retry
          </button>
        </div>
      </div>
    );
  }

  const students = data?.students || [];
  const count = data?.count || students.length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-heading text-xl font-bold text-slate-900 dark:text-white">
            Access OFF Students
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Students whose app access is blocked. Turn access back ON to restore login.
          </p>
        </div>
        <Link to="/students" className="inline-flex items-center gap-2 text-[#2563EB] font-medium">
          <ArrowLeft className="w-4 h-4" /> Back to students
        </Link>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <Stat label="Blocked Students" value={count} tone="text-rose-600 dark:text-rose-400" />
        <Stat
          label="Avg Attendance"
          value={
            count > 0
              ? Math.round(
                  students.reduce((a, s) => a + (s.attendance || 0), 0) / count,
                )
              : 0
          }
          suffix="%"
        />
        <Stat
          label="Avg Study Hrs/Day"
          value={
            count > 0
              ? (
                  students.reduce((a, s) => a + (s.studyHours || 0), 0) /
                  count
                ).toFixed(1)
              : 0
          }
          suffix="h"
        />
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.18em] font-semibold text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
              <th className="px-5 py-3">Student</th>
              <th className="px-5 py-3">Batch</th>
              <th className="px-5 py-3">Group</th>
              <th className="px-5 py-3">Attendance</th>
              <th className="px-5 py-3">Blocked Since</th>
              <th className="px-5 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {students.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-16 text-center text-sm text-slate-500 dark:text-slate-400">
                  No students with access OFF. All students can log in.
                </td>
              </tr>
            ) : (
              students.map((s) => {
                const isPending = accessMutation.isPending;
                return (
                  <tr
                    key={s.id}
                    className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors"
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="grid h-9 w-9 place-items-center rounded-full bg-rose-50 text-xs text-rose-600">
                          {String(s.name || s.id)
                            .split(' ')
                            .map((x) => x[0])
                            .slice(0, 2)
                            .join('')}
                        </span>
                        <div>
                          <div className="font-semibold text-slate-900 dark:text-white">
                            {s.name}
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {s.studentId}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">
                      {s.batch}
                    </td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">
                      {s.group}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2 min-w-[100px]">
                        <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-rose-500"
                            style={{ width: `${Math.min(s.attendance || 0, 100)}%` }}
                          />
                        </div>
                        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 w-8 text-right">
                          {s.attendance || 0}%
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-slate-700 dark:text-slate-300">
                      {s.accessUpdatedAt ? String(s.accessUpdatedAt).slice(0, 10) : '—'}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <button
                        type="button"
                        disabled={isPending}
                        onClick={() =>
                          accessMutation.mutate({
                            id: s.id,
                            name: s.name,
                            enabled: true,
                            reason: '',
                          })
                        }
                        className={cn(
                          'h-8 px-3 rounded-lg border border-emerald-200 text-emerald-700 hover:bg-emerald-50 text-xs font-semibold disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300 dark:hover:bg-emerald-950/30',
                        )}
                        data-testid={`access-turn-on-${s.id}`}
                      >
                        {isPending ? (
                          <Loader2 className="w-3.5 h-3.5" />
                        ) : (
                          <Power className="w-3.5 h-3.5" />
                        )}
                        {isPending ? ' ON…' : ' Turn ON'}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {students.length > 0 && (
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Turning access ON restores the student's app login immediately.
        </div>
      )}
    </div>
  );
}
