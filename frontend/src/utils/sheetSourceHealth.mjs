/** Status of the displayed API response, never a claim of background sync. */
export function sheetSourceHealth(source) {
  const s = source && typeof source === 'object' ? source : {};
  const formRead = typeof s.formReadOk === 'boolean' ? s.formReadOk : s.formRead;
  const warnings = [];
  if (s.roster === 'Mongo fallback') warnings.push('Sheet roster unavailable; saved roster is in use. Verify group membership before decisions.');
  if (formRead === false) warnings.push('Tracker Sheet read unavailable; counts and ranks may be incomplete. Do not infer absence from missing data.');
  if (warnings.length) return { state: 'warning', title: 'Sheet data needs verification', detail: warnings.join(' ') };
  if (s.roster === 'Students Sheet' && formRead === true) return {
    state: 'read-ok', title: 'Sheet read succeeded for this response',
    detail: 'Students Sheet roster and tracker Sheet were read alongside app logs. This does not verify device sync or finalized podiums.'
  };
  return { state: 'unknown', title: 'Sheet source status not fully reported', detail: 'Do not assume this response contains a verified Sheet roster and complete tracker history.' };
}
