// Local workbook authoring only. No API, publication or inferred academic marks.
export const emptyQuestion = () => ({ prompt: '', modelAnswer: '', referenceLabel: '', page: 1, workbookPage: 1, rubricText: '', sourceVerified: false, format: 'written', optionsText: '', correctOptionId: '', blanksText: '', matchingLeftText: '', matchingRightText: '' });
const lines = value => String(value || '').split('\n').map(s => s.trim()).filter(Boolean);
const identifier = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,40}$/.test(value);
const split = (line, message) => { const at = line.indexOf('|'); if (at < 1 || !line.slice(at + 1).trim()) throw new Error(message); return [line.slice(0, at).trim(), line.slice(at + 1).trim()]; };
const text = value => { if (!value || value.length > 500) throw new Error('Objective labels and accepted answers must contain 1–500 characters.'); return value; };
function options(value) {
  const result = lines(value).map(line => { const [id, label] = split(line, 'Options must be: option ID | displayed text'); if (!identifier(id)) throw new Error('Option IDs must use letters, numbers, underscore or hyphen.'); return { id, text: text(label) }; });
  if (result.length < 2 || result.length > 20 || new Set(result.map(o => o.id)).size !== result.length) throw new Error('Supply 2–20 options with unique IDs.');
  return result;
}
export function objectivePayload(question, rubric) {
  const format = question.format || 'written';
  if (format === 'written') return { format };
  if (format === 'mcq') {
    if (rubric.length !== 1) throw new Error('An MCQ needs exactly one explicit rubric/mark line.');
    const choices = options(question.optionsText), correct = String(question.correctOptionId || '').trim();
    if (!choices.some(o => o.id === correct)) throw new Error('Choose the approved correct option ID from the supplied options.');
    return { format, objective: { options: choices, correctOptionId: correct } };
  }
  if (format === 'blanks') {
    const rows = lines(question.blanksText);
    if (rows.length !== rubric.length) throw new Error('Supply one blank line per rubric point, in the same order.');
    const slots = rows.map((line, i) => {
      const [label, answers] = split(line, 'Blanks must be: displayed blank label | approved answer ;; optional alias');
      const acceptedAnswers = answers.split(';;').map(a => a.trim());
      if (!acceptedAnswers.length || acceptedAnswers.length > 8 || acceptedAnswers.some(a => !a || a.length > 500) || new Set(acceptedAnswers.map(a => a.normalize('NFKC').toLowerCase().replace(/\s+/g, ' ').trim())).size !== acceptedAnswers.length) throw new Error('Use 1–8 distinct, explicit approved answers per blank.');
      return { id: rubric[i].id, text: text(label), acceptedAnswers };
    });
    return { format, objective: { slots } };
  }
  if (format === 'matching') {
    const right = options(question.matchingRightText), rows = lines(question.matchingLeftText);
    if (rows.length !== rubric.length || rows.length !== right.length) throw new Error('Matching needs one left item per rubric point and the same number of right options.');
    const matches = {}, left = rows.map((line, i) => {
      const [label, correct] = split(line, 'Left items must be: displayed text | approved right-option ID');
      if (!right.some(o => o.id === correct)) throw new Error('Every match must refer to a supplied right-option ID.');
      matches[rubric[i].id] = correct; return { id: rubric[i].id, text: text(label) };
    });
    if (new Set(Object.values(matches)).size !== rows.length) throw new Error('Matching keys must be one-to-one; do not reuse a right-option ID.');
    return { format, objective: { left, right, matches } };
  }
  throw new Error('Unsupported question format. Existing content was not changed.');
}
export function workbookPayload(form, questions) {
  return {
    title: form.title.trim(), subject: form.subject, groups: form.groups,
    batches: form.batches.split('\n').map(s => s.trim()).filter(Boolean), sourceUrl: form.sourceUrl.trim(),
    questions: questions.map((q, i) => {
      const rubric = lines(q.rubricText).map((line, n) => {
        const at = line.indexOf('|'), marks = Number(line.slice(0, at).trim());
        if (at < 1 || !Number.isFinite(marks) || marks <= 0 || marks > 20) throw new Error('Rubric lines must be: marks | concept to credit (up to 20 marks per point)');
        return { id: `p${n + 1}`, marks, concept: line.slice(at + 1).trim() };
      });
      if (!rubric.length || rubric.length > 20 || rubric.reduce((sum, p) => sum + p.marks, 0) > 100) throw new Error('Add 1–20 explicit rubric points totalling at most 100 marks.');
      return { id: `q${i + 1}`, prompt: q.prompt.trim(), modelAnswer: q.modelAnswer.trim(), referenceLabel: q.referenceLabel.trim(), page: Number(q.page), workbookPage: Number(q.workbookPage || 1), rubric, maxMarks: rubric.reduce((sum, p) => sum + p.marks, 0), sourceVerified: q.sourceVerified === true, ...objectivePayload(q, rubric) };
    })
  };
}
export function cloneWorkbookQuestion(question) {
  const q = { ...emptyQuestion(), ...question, sourceVerified: false, rubricText: question.rubric.map(p => `${p.marks} | ${p.concept}`).join('\n') };
  const format = q.format || 'written', objective = question.objective;
  if (!['written', 'mcq', 'blanks', 'matching'].includes(format)) throw new Error('Unsupported question format. Original workbook remains unchanged.');
  if (format === 'written') return q;
  if (!objective) throw new Error('The saved objective key is missing. Original workbook remains unchanged.');
  if (format === 'mcq') { q.optionsText = objective.options.map(o => `${o.id} | ${o.text}`).join('\n'); q.correctOptionId = objective.correctOptionId; }
  else if (format === 'blanks') q.blanksText = question.rubric.map(p => {
    const slot = objective.slots.find(s => s.id === p.id);
    if (!slot || slot.text.includes('|') || slot.acceptedAnswers.some(a => a.includes(';;'))) throw new Error('This key requires a structured editor; no content was silently converted.');
    return `${slot.text} | ${slot.acceptedAnswers.join(' ;; ')}`;
  }).join('\n');
  else if (format === 'matching') {
    q.matchingRightText = objective.right.map(o => `${o.id} | ${o.text}`).join('\n');
    q.matchingLeftText = question.rubric.map(p => { const item = objective.left.find(x => x.id === p.id); if (!item || item.text.includes('|')) throw new Error('This matching key requires a structured editor.'); return `${item.text} | ${objective.matches[p.id]}`; }).join('\n');
  } else throw new Error('Unsupported question format. Original workbook remains unchanged.');
  // Remapping rubric IDs in a NEW draft must preserve the key, never reuse a foreign ID.
  objectivePayload(q, question.rubric.map((p, i) => ({ ...p, id: `p${i + 1}` })));
  return q;
}

// Full readback comparison, excluding server metadata but not marks or keys.
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value;
export function matchesWorkbookPayload(payload, book) {
  if (!book || !Array.isArray(book.questions) || book.questions.length !== payload.questions.length) return false;
  const expected = { ...payload, questions: payload.questions.map(q => ({ ...q, objective: q.objective ?? null })) };
  const actual = Object.fromEntries(Object.keys(payload).map(k => [k, k === 'questions' ? book.questions.map((q, i) => Object.fromEntries(Object.keys(expected.questions[i]).map(field => [field, field === 'objective' ? q[field] ?? null : q[field]]))) : book[k]]));
  return JSON.stringify(canonical(expected)) === JSON.stringify(canonical(actual));
}
