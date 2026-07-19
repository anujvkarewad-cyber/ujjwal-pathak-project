import { cn } from '@/utils/format';

export function Skeleton({ className, ...props }) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800/60',
        className
      )}
      {...props}
    />
  );
}

export function CardSkeleton({ height = 'h-32' }) {
  return (
    <div className={cn('bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5', height)}>
      <Skeleton className="w-10 h-10 mb-4" />
      <Skeleton className="h-3 w-24 mb-2" />
      <Skeleton className="h-8 w-20" />
    </div>
  );
}
