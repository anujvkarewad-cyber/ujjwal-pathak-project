// Session-scoped memory of the reviewer's queue context.
// Question Review uses it for Previous/Next (including crossing queue pages),
// and Review Queue uses it to restore your filters + page when you come Back —
// so you land on the question you left, never back at question 1.

const KEYS = {
  ids: 'reviewQueueIds',
  index: 'reviewQueueIndex',
  page: 'reviewQueuePage',
  size: 'reviewQueuePageSize',
  total: 'reviewQueueTotal',
  filters: 'reviewQueueFilters',
};

export const DEFAULT_QUEUE_SIZE = 50;

export function loadQueueContext() {
  const empty = { ids: [], index: -1, page: 1, size: DEFAULT_QUEUE_SIZE, total: 0, filters: {} };
  try {
    const ids = JSON.parse(sessionStorage.getItem(KEYS.ids) || '[]');
    const filters = JSON.parse(sessionStorage.getItem(KEYS.filters) || '{}');
    return {
      ids: Array.isArray(ids) ? ids : [],
      index: Number(sessionStorage.getItem(KEYS.index) ?? -1),
      page: Number(sessionStorage.getItem(KEYS.page) || 1) || 1,
      size: Number(sessionStorage.getItem(KEYS.size) || DEFAULT_QUEUE_SIZE) || DEFAULT_QUEUE_SIZE,
      total: Number(sessionStorage.getItem(KEYS.total) || 0) || 0,
      filters: filters && typeof filters === 'object' ? filters : {},
    };
  } catch {
    return empty;
  }
}

export function saveQueueContext(ctx = {}) {
  try {
    sessionStorage.setItem(KEYS.ids, JSON.stringify(ctx.ids || []));
    sessionStorage.setItem(KEYS.index, String(ctx.index ?? -1));
    sessionStorage.setItem(KEYS.page, String(ctx.page || 1));
    sessionStorage.setItem(KEYS.size, String(ctx.size || DEFAULT_QUEUE_SIZE));
    sessionStorage.setItem(KEYS.total, String(ctx.total || 0));
    if (ctx.filters) sessionStorage.setItem(KEYS.filters, JSON.stringify(ctx.filters));
  } catch {}
}

// Used by Review Queue to keep the saved filters/page fresh as the reviewer
// changes them, without touching the saved ids/index.
export function saveQueueListState({ filters, page, size }) {
  try {
    if (filters) sessionStorage.setItem(KEYS.filters, JSON.stringify(filters));
    if (page) sessionStorage.setItem(KEYS.page, String(page));
    if (size) sessionStorage.setItem(KEYS.size, String(size));
  } catch {}
}

export function clearQueueContext() {
  try {
    Object.values(KEYS).forEach((k) => sessionStorage.removeItem(k));
  } catch {}
}

// Build /api/content/queue params the same way Review Queue does.
export function queueFiltersToParams(filters = {}, limit, offset) {
  const hw = filters.hasWarnings;
  return {
    subject: filters.subject || undefined,
    chapterId: filters.chapterId || undefined,
    questionType: filters.questionType || undefined,
    difficulty: filters.difficulty || undefined,
    status: filters.status || undefined,
    hasWarnings: hw === '' || hw === null || hw === undefined ? undefined : hw === true || hw === 'true',
    limit,
    offset,
  };
}
