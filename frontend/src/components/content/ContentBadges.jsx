// Shared badges for the AI Content + Analytics areas.
import { cn } from '@/utils/format';

const STATUS_STYLES = {
  generated: 'bg-slate-100 text-slate-600 border-slate-200',
  auto_validated: 'bg-sky-50 text-sky-700 border-sky-200',
  needs_review: 'bg-amber-50 text-amber-700 border-amber-200',
  changes_requested: 'bg-orange-50 text-orange-700 border-orange-200',
  rejected: 'bg-rose-50 text-rose-700 border-rose-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  release_candidate: 'bg-violet-50 text-violet-700 border-violet-200',
  published: 'bg-blue-50 text-blue-700 border-blue-200',
  superseded: 'bg-slate-100 text-slate-400 border-slate-200',
};

export function StatusBadge({ status, className }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border',
        STATUS_STYLES[status] || STATUS_STYLES.generated,
        className
      )}
      data-testid={`status-badge-${status}`}
    >
      {String(status).replace(/_/g, ' ')}
    </span>
  );
}

const BAND_STYLES = {
  'Not assessed': 'bg-slate-100 text-slate-500 border-slate-300',
  Weak: 'bg-rose-50 text-rose-700 border-rose-200',
  Medium: 'bg-amber-50 text-amber-700 border-amber-200',
  Strong: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  Mastered: 'bg-blue-50 text-blue-700 border-blue-200',
};

export const BAND_COLORS = {
  'Not assessed': '#CBD5E1',
  Weak: '#F87171',
  Medium: '#FBBF24',
  Strong: '#34D399',
  Mastered: '#3B82F6',
};

export function BandBadge({ band, inactive, className }) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border',
        BAND_STYLES[band] || BAND_STYLES['Not assessed'],
        className
      )}
    >
      {inactive ? `${band} · inactive` : band}
    </span>
  );
}

export function DifficultyBadge({ difficulty }) {
  const styles = {
    easy: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    moderate: 'bg-amber-50 text-amber-700 border-amber-200',
    hard: 'bg-rose-50 text-rose-700 border-rose-200',
  };
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border', styles[difficulty] || styles.moderate)}>
      {difficulty}
    </span>
  );
}

export function TypeBadge({ questionType }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border bg-slate-50 text-slate-600 border-slate-200">
      {questionType === 'scenario_mcq' ? 'scenario MCQ' : 'plain MCQ'}
    </span>
  );
}
