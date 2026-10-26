/** Protected membership bridge. Merge into the EXISTING owner-authorized admin
 * script; do not create a public replacement project or run setup/seed routines.
 * Requires Script Property STUDENT_IMPORT_KEY matching backend server secret.
 * Called only by the new explicit mentor transfer endpoint. No credentials/logs
 * or other student columns are copied, returned or modified.
 */
function mentorChangeMembership_(payload) {
  const props = PropertiesService.getScriptProperties();
  const secret = props.getProperty('STUDENT_IMPORT_KEY');
  if (!secret || !payload || String(payload.adminKey || '') !== secret) return { success: false, code: 'unauthorized' };
  const sid = String(payload.studentId || '').trim().toUpperCase();
  const batch = String(payload.batch || '').trim();
  const group = String(payload.group || '').trim();
  const op = String(payload.operationId || '');
  const allowedBatches = ['Before Result Batch 1', 'Before Result Batch 2', 'After Result Batch 1', 'After Result Batch 2'];
  if (!/^UMP\d{4,}$/.test(sid) || ['UMP0000', 'UMP9999'].indexOf(sid) >= 0 || allowedBatches.indexOf(batch) < 0 || ['Group 1', 'Group 2', 'Both'].indexOf(group) < 0 || !/^[a-zA-Z0-9:-]{10,100}$/.test(op)) return { success: false, code: 'invalid_request' };
  const expectedBatch = String(payload.expectedBatch || '').trim();
  const expectedGroup = String(payload.expectedGroup || '').trim();
  if (!expectedBatch || !expectedGroup) return { success: false, code: 'expected_membership_required' };
  const operationKey = 'membership.' + Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, op).map(function(b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
  const signature = JSON.stringify([sid, expectedBatch, expectedGroup, batch, group]);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return { success: false, code: 'busy' };
  try {
    const saved = props.getProperty(operationKey);
    if (saved) {
      const receipt = JSON.parse(saved);
      if (receipt.signature !== signature) return { success: false, code: 'operation_conflict' };
      return receipt.result || { success: false, code: 'needs_reconciliation' };
    }
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Students');
    if (!sheet) return { success: false, code: 'missing_students_tab' };
    const rows = sheet.getDataRange().getDisplayValues();
    const h = rows[0].map(function(v) { return String(v).trim().toLowerCase(); });
    function col(names) { for (let i = 0; i < names.length; i++) if (h.indexOf(names[i]) >= 0) return h.indexOf(names[i]); return -1; }
    const idCol = col(['student id', 'studentid', 'id']), batchCol = col(['batch']), groupCol = col(['group', 'groups']);
    if ([idCol, batchCol, groupCol].some(function(v) { return v < 0; })) return { success: false, code: 'schema_mismatch' };
    const matches = [];
    for (let i = 1; i < rows.length; i++) if (String(rows[i][idCol]).trim().toUpperCase() === sid) matches.push(i);
    if (matches.length !== 1) return { success: false, code: 'missing_or_duplicate_id' };
    const n = matches[0], previousBatch = String(rows[n][batchCol]).trim(), previousGroup = String(rows[n][groupCol]).trim();
    if (previousBatch !== expectedBatch || previousGroup !== expectedGroup) return { success: false, code: 'membership_conflict' };
    // Record intent before writes; an interrupted invocation can never silently
    // resend the command. This is not a cross-Sheet/Mongo transaction.
    props.setProperty(operationKey, JSON.stringify({ signature: signature, state: 'running' }));
    try {
      sheet.getRange(n + 1, batchCol + 1).setValue(batch);
      sheet.getRange(n + 1, groupCol + 1).setValue(group);
      SpreadsheetApp.flush();
      if (String(sheet.getRange(n + 1, batchCol + 1).getDisplayValue()).trim() !== batch || String(sheet.getRange(n + 1, groupCol + 1).getDisplayValue()).trim() !== group) throw new Error('membership_readback_mismatch');
      const result = { success: true, studentId: sid, previousBatch: previousBatch, previousGroup: previousGroup, batch: batch, group: group };
      props.setProperty(operationKey, JSON.stringify({ signature: signature, state: 'completed', result: result }));
      return result;
    } catch (_) {
      // Retain running marker. Do not overwrite another editor's corrections
      // or claim an automatic rollback. Backend retains a reconciliation lock.
      return { success: false, code: 'needs_reconciliation' };
    }
  } finally { lock.releaseLock(); }
}

function mentorMembershipCapabilities_(payload) {
  const secret = PropertiesService.getScriptProperties().getProperty('STUDENT_IMPORT_KEY');
  if (!secret || !payload || String(payload.adminKey || '') !== secret) return { success: false, code: 'unauthorized' };
  return { success: true, membershipVersion: 2, reconciliationFence: true, destinationOnly: true, bulkAtomic: false };
}

/** Close a specific operation under the same lock before reconciliation reads.
 * A delayed original HTTP invocation sees the closed receipt and cannot write
 * after the mentor readback releases its Mongo lock. Membership cells untouched.
 */
function mentorMembershipFence_(payload) {
  const props = PropertiesService.getScriptProperties();
  const secret = props.getProperty('STUDENT_IMPORT_KEY');
  if (!secret || !payload || String(payload.adminKey || '') !== secret) return { success: false, code: 'unauthorized' };
  const sid = String(payload.studentId || '').trim().toUpperCase();
  const op = String(payload.operationId || '');
  if (!/^UMP\d{4,}$/.test(sid) || !/^[a-zA-Z0-9:-]{10,100}$/.test(op)) return { success: false, code: 'invalid_request' };
  const signature = JSON.stringify([sid, String(payload.expectedBatch || '').trim(), String(payload.expectedGroup || '').trim(), String(payload.batch || '').trim(), String(payload.group || '').trim()]);
  const key = 'membership.' + Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, op).map(function(b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return { success: false, code: 'busy' };
  try {
    const saved = props.getProperty(key);
    if (saved && JSON.parse(saved).signature !== signature) return { success: false, code: 'operation_conflict' };
    if (!saved || JSON.parse(saved).state !== 'completed') props.setProperty(key, JSON.stringify({ signature: signature, state: 'closed' }));
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Students');
    if (!sheet) return { success: false, code: 'missing_students_tab' };
    const rows = sheet.getDataRange().getDisplayValues();
    const h = rows[0].map(function(v) { return String(v).trim().toLowerCase(); });
    function col(names) { for (let i = 0; i < names.length; i++) if (h.indexOf(names[i]) >= 0) return h.indexOf(names[i]); return -1; }
    const id = col(['student id', 'studentid', 'id']), batch = col(['batch']), group = col(['group', 'groups']);
    if ([id, batch, group].some(function(v) { return v < 0; })) return { success: false, code: 'schema_mismatch' };
    const matches = rows.slice(1).filter(function(r) { return String(r[id]).trim().toUpperCase() === sid; });
    if (matches.length !== 1) return { success: false, code: 'missing_or_duplicate_id' };
    return { success: true, operationClosed: true, studentId: sid, batch: String(matches[0][batch]).trim(), group: String(matches[0][group]).trim() };
  } finally { lock.releaseLock(); }
}
