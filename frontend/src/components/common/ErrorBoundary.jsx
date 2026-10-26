// Catches a render crash in one screen so it does not take the whole dashboard down.
//
// Why this exists: on 17-Oct-2026 a stale helper name in the Submissions table made the
// entire page blank - white screen, no message, nothing for the mentor to act on, and
// nothing in the console he would think to open. A component that throws should lose its
// own section, not the app.
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // The browser console keeps the stack; this is the part a mentor can read and quote.
    // eslint-disable-next-line no-console
    console.error(`[${this.props.label || 'screen'}] failed to render`, error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const message = String(this.state.error?.message || this.state.error || 'unknown error');
    return (
      <div
        data-testid="screen-error"
        className="rounded-xl border border-rose-200 dark:border-rose-500/30 bg-rose-50/70 dark:bg-rose-500/10 px-4 py-4 text-sm text-rose-800 dark:text-rose-200"
      >
        <div className="font-semibold">
          {this.props.label ? `${this.props.label}: this section could not be shown` : 'This section could not be shown'}
        </div>
        <div className="mt-1 text-xs leading-snug opacity-90">
          The rest of the dashboard still works. Tell the developer this line and it will be fixed:
        </div>
        <code className="mt-2 block px-2 py-1.5 rounded-md bg-white/70 dark:bg-slate-900/60 border border-rose-200/70 dark:border-rose-500/20 font-mono text-[11px] break-all">
          {message}
        </code>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-3 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#2563EB] text-white hover:bg-[#1d4ed8]"
        >
          Try again
        </button>
      </div>
    );
  }
}
