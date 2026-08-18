// Global error boundary: prevents a single page crash (e.g. an analytics
// fetch returning bad data) from unmounting the whole app into a blank white
// screen. Shows a friendly fallback with a retry button instead.
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(err) {
    return { hasError: true, message: err?.message || 'Unexpected error' };
  }

  componentDidCatch(err) {
    // eslint-disable-next-line no-console
    console.error('ErrorBoundary caught:', err);
  }

  handleReset = () => {
    this.setState({ hasError: false, message: '' });
    if (typeof this.props.onReset === 'function') this.props.onReset();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="flex h-screen items-center justify-center bg-slate-50 dark:bg-slate-950 p-6"
          data-testid="error-boundary"
        >
          <div className="max-w-md w-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 text-center">
            <div className="mx-auto w-12 h-12 rounded-full bg-rose-50 dark:bg-rose-500/10 flex items-center justify-center text-2xl mb-4">
              ⚠️
            </div>
            <h2 className="font-heading text-lg font-semibold text-slate-900 dark:text-white mb-1">
              Something went wrong
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-5">
              This screen hit an error and couldn’t render.
              {this.state.message ? (
                <span className="block mt-1 font-mono text-xs text-rose-500 break-words">{this.state.message}</span>
              ) : null}
            </p>
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center justify-center rounded-lg bg-[#2563EB] hover:bg-blue-600 text-white text-sm font-semibold px-4 py-2 transition-colors"
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
