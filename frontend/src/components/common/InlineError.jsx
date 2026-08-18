// Small inline error notice used across analytics tabs. Keeps the page
// rendered (never a white screen) and tells the mentor what happened.
export default function InlineError({ title = 'Couldn’t load this view', error }) {
  return (
    <div
      className="rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50 dark:bg-rose-500/10 p-5"
      data-testid="inline-error"
    >
      <h3 className="font-heading font-semibold text-rose-700 dark:text-rose-300 mb-1">{title}</h3>
      <p className="text-sm text-rose-600 dark:text-rose-300">
        {error?.message || 'Something went wrong. Please try again.'}
      </p>
    </div>
  );
}
