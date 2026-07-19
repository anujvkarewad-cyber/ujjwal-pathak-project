/**
 * Ujjwal Pathak Mentorship — Dashboard Backend (Google Apps Script)
 * -----------------------------------------------------------------
 * Sheet: https://docs.google.com/spreadsheets/d/1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc
 *
 * SETUP (one time)
 *   1. Open the Sheet → Extensions → Apps Script.
 *   2. Delete any placeholder code, paste this entire file.
 *   3. Save (Ctrl/Cmd + S). Project name: "Mentor Dashboard API".
 *   4. Run `setupSheets` once (top toolbar → select function → Run).
 *      Approve the permission dialog (Google will ask for edit access to this sheet).
 *      This creates the Students, Announcements, MentorNotes, Mentor,
 *      Notifications, MCQ, and Attendance tabs (if missing) with headers.
 *   5. Deploy → New deployment → Type: Web app.
 *        - Execute as: Me
 *        - Who has access: Anyone
 *      Click Deploy → Copy the "Web app URL" (ending in /exec).
 *   6. Paste that URL back to the developer / add to frontend .env as
 *      REACT_APP_APPS_SCRIPT_URL=<paste-url>
 *
 * When a student submits the linked Google Form, the "Form responses 1"
 * tab receives a new row and the dashboard reflects it on next refresh.
 * No re-deployment needed.
 * ----------------------------------------------------------------- */

const CONFIG = {
  FORM_RESPONSES_SHEET: 'Form responses 1',
  STUDENTS_SHEET: 'Students',
  ANNOUNCEMENTS_SHEET: 'Announcements',
  MENTOR_NOTES_SHEET: 'MentorNotes',
  MENTOR_SHEET: 'Mentor',
  NOTIFICATIONS_SHEET: 'Notifications',
  MCQ_SHEET: 'MCQ',
  ATTENDANCE_SHEET: 'Attendance',
  DEFAULT_BATCH: 'Super 30',
  DEFAULT_ATTEMPT: 'Sept 2026',
  DEFAULT_GROUP: 'Both Groups',
  DEFAULT_LEVEL: 'CA Intermediate',
  DEFAULT_STATUS: 'Active',
  TRACKER_DAYS: 14,
  DEFAULT_AVATAR: 'https://ui-avatars.com/api/?background=2563EB&color=fff&size=200&name=',
};

// ─────────────────────────────────────────────────────────────────────────
// PUBLIC ENTRY POINTS — doPost / doGet
// ─────────────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    const body = e && e.postData ? JSON.parse(e.postData.contents) : {};
    const result = handleAction(body.action, body.payload || {});
    return jsonOut({ result });
  } catch (err) {
    return jsonOut({ error: String((err && err.message) || err) });
  }
}

function doGet(e) {
  const action = (e && e.parameter && e.parameter.action) || '';
  if (!action) {
    return jsonOut({
      ok: true,
      message: 'Ujjwal Pathak Mentorship API is live. Use POST with { action, payload }.',
      version: '1.0.0',
    });
  }
  try {
    const result = handleAction(action, {});
    return jsonOut({ result });
  } catch (err) {
    return jsonOut({ error: String((err && err.message) || err) });
  }
}

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ─────────────────────────────────────────────────────────────────────────
// ROUTER
// ─────────────────────────────────────────────────────────────────────────

function handleAction(action, payload) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureAllSheets(ss); // idempotent — safe on every call

  switch (action) {
    case 'students.list': return { students: listStudents(ss), options: options_() };
    case 'students.get': return getStudent(ss, payload.id);
    case 'students.addNote': return addNote(ss, payload.id, payload.note);

    case 'dashboard.kpis': return kpis(ss);
    case 'dashboard.recentActivity': return recentActivity(ss);
    case 'dashboard.weeklyStudy': return weeklyStudy(ss);
    case 'dashboard.attendanceTrend': return attendanceTrend(ss);
    case 'dashboard.performanceMix': return performanceMix(ss);
    case 'dashboard.batchOverview': return batchOverview(ss);
    case 'dashboard.upcomingTasks': return upcomingTasks(ss);

    case 'tracker.day': return trackerDay(ss, payload.dayIndex, payload.batch);
    case 'leaderboard.list': return leaderboard(ss, payload.mode || 'overall');

    case 'announcements.list': return listAnnouncements(ss);
    case 'announcements.create': return createAnnouncement(ss, payload);
    case 'announcements.togglePin': return togglePinAnnouncement(ss, payload.id);

    case 'reports.batch': return batchOverview(ss);
    case 'reports.students': return studentReport(ss);

    case 'mentor.get': return getMentor(ss);
    case 'mentor.update': return updateMentor(ss, payload);
    case 'notifications.get': return getNotifications(ss);
    case 'notifications.update': return updateNotifications(ss, payload);

    default: throw new Error('Unknown action: ' + action);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// SETUP / SEEDING
// ─────────────────────────────────────────────────────────────────────────

function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ensureAllSheets(ss);
  seedMentor(ss);
  seedNotifications(ss);
  seedAnnouncements(ss);
  syncStudentsFromForm(ss);
  return 'Setup complete. ' + listStudents(ss).length + ' students in master.';
}

function ensureAllSheets(ss) {
  ensureSheet(ss, CONFIG.STUDENTS_SHEET, ['id', 'name', 'email', 'phone', 'avatar', 'batch', 'attempt', 'group', 'level', 'city', 'joinedOn', 'status']);
  ensureSheet(ss, CONFIG.ANNOUNCEMENTS_SHEET, ['id', 'title', 'body', 'audience', 'date', 'pinned', 'author']);
  ensureSheet(ss, CONFIG.MENTOR_NOTES_SHEET, ['id', 'studentId', 'date', 'note']);
  ensureSheet(ss, CONFIG.MENTOR_SHEET, ['key', 'value']);
  ensureSheet(ss, CONFIG.NOTIFICATIONS_SHEET, ['key', 'value']);
  ensureSheet(ss, CONFIG.MCQ_SHEET, ['date', 'studentId', 'mcqCount', 'mcqAccuracy']);
  ensureSheet(ss, CONFIG.ATTENDANCE_SHEET, ['date', 'studentId', 'present']);
}

function ensureSheet(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(headers);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold').setBackground('#EFF6FF').setFontColor('#1E40AF');
    sh.setFrozenRows(1);
  } else if (sh.getLastRow() === 0) {
    sh.appendRow(headers);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold').setBackground('#EFF6FF').setFontColor('#1E40AF');
    sh.setFrozenRows(1);
  }
  return sh;
}

function seedMentor(ss) {
  const sh = ss.getSheetByName(CONFIG.MENTOR_SHEET);
  if (sh.getLastRow() > 1) return;
  const rows = [
    ['name', 'Ujjwal Pathak'],
    ['email', 'mentor@upmentorship.in'],
    ['avatar', 'https://images.unsplash.com/photo-1589386417686-0d34b5903d23?crop=entropy&cs=srgb&fm=jpg&q=85&w=200'],
  ];
  sh.getRange(2, 1, rows.length, 2).setValues(rows);
}

function seedNotifications(ss) {
  const sh = ss.getSheetByName(CONFIG.NOTIFICATIONS_SHEET);
  if (sh.getLastRow() > 1) return;
  const rows = [
    ['emailNotif', 'true'],
    ['smsNotif', 'false'],
    ['dailyDigest', 'true'],
  ];
  sh.getRange(2, 1, rows.length, 2).setValues(rows);
}

function seedAnnouncements(ss) {
  const sh = ss.getSheetByName(CONFIG.ANNOUNCEMENTS_SHEET);
  if (sh.getLastRow() > 1) return;
  const today = fmtDate_(new Date());
  const rows = [
    ['ANN-001', 'Welcome to the Mentor Dashboard', 'This dashboard is now live and connected to your Google Sheet. Daily tracker submissions update automatically.', 'All Batches', today, true, 'Ujjwal Pathak'],
  ];
  sh.getRange(2, 1, rows.length, 7).setValues(rows);
}

// Reads unique student IDs from the Form responses sheet and appends any
// missing ones to the Students master with sensible defaults.
function syncStudentsFromForm(ss) {
  const formSh = ss.getSheetByName(CONFIG.FORM_RESPONSES_SHEET);
  if (!formSh) return;
  const studentsSh = ss.getSheetByName(CONFIG.STUDENTS_SHEET);
  const existing = new Set(
    studentsSh.getLastRow() > 1
      ? studentsSh.getRange(2, 1, studentsSh.getLastRow() - 1, 1).getValues().map(r => String(r[0]).trim().toUpperCase())
      : []
  );

  const responses = readForm_(formSh);
  const idsSeen = new Set();
  responses.forEach(r => idsSeen.add(r.studentId));

  const toAppend = [];
  const today = fmtDate_(new Date());
  Array.from(idsSeen).sort().forEach(id => {
    if (!id) return;
    if (existing.has(id)) return;
    const name = displayNameFromId_(id);
    toAppend.push([
      id, name, '', '', CONFIG.DEFAULT_AVATAR + encodeURIComponent(name),
      CONFIG.DEFAULT_BATCH, CONFIG.DEFAULT_ATTEMPT, CONFIG.DEFAULT_GROUP,
      CONFIG.DEFAULT_LEVEL, '', today, CONFIG.DEFAULT_STATUS
    ]);
  });
  if (toAppend.length) {
    studentsSh.getRange(studentsSh.getLastRow() + 1, 1, toAppend.length, 12).setValues(toAppend);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// DATA READERS
// ─────────────────────────────────────────────────────────────────────────

// Reads Form responses 1 → normalized array of daily submissions.
function readForm_(sh) {
  if (!sh || sh.getLastRow() < 2) return [];
  const values = sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
  const out = [];
  values.forEach(row => {
    const timestamp = row[0];
    const rawId = row[1];
    const studied = row[2];
    const hoursRaw = row[3];
    const proofUrl = row[4];
    const studyDate = row[5];
    if (!rawId && !studied) return;
    const id = normalizeId_(rawId);
    const hours = parseHours_(hoursRaw);
    const date = parseDate_(studyDate) || parseDate_(timestamp);
    if (!date) return;
    out.push({
      timestamp: timestamp instanceof Date ? timestamp : parseDate_(timestamp),
      studentId: id,
      rawId: String(rawId || '').trim(),
      studied: String(studied || ''),
      hours,
      proofUrl: String(proofUrl || ''),
      date, // yyyy-MM-dd
    });
  });
  return out;
}

function readStudents_(ss) {
  const sh = ss.getSheetByName(CONFIG.STUDENTS_SHEET);
  if (sh.getLastRow() < 2) return [];
  const values = sh.getRange(2, 1, sh.getLastRow() - 1, 12).getValues();
  return values.map(r => ({
    id: String(r[0]).trim(),
    name: String(r[1] || '').trim() || displayNameFromId_(r[0]),
    email: String(r[2] || ''),
    phone: String(r[3] || ''),
    avatar: String(r[4] || '') || (CONFIG.DEFAULT_AVATAR + encodeURIComponent(String(r[1] || r[0]))),
    batch: String(r[5] || CONFIG.DEFAULT_BATCH),
    attempt: String(r[6] || CONFIG.DEFAULT_ATTEMPT),
    group: String(r[7] || CONFIG.DEFAULT_GROUP),
    level: String(r[8] || CONFIG.DEFAULT_LEVEL),
    city: String(r[9] || ''),
    joinedOn: fmtDate_(r[10]) || '',
    status: String(r[11] || CONFIG.DEFAULT_STATUS),
  }));
}

function readMcq_(ss) {
  const sh = ss.getSheetByName(CONFIG.MCQ_SHEET);
  if (sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, 4).getValues().map(r => ({
    date: fmtDate_(r[0]),
    studentId: normalizeId_(r[1]),
    mcqCount: Number(r[2]) || 0,
    mcqAccuracy: Number(r[3]) || 0,
  }));
}

function readAttendance_(ss) {
  const sh = ss.getSheetByName(CONFIG.ATTENDANCE_SHEET);
  if (sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, 3).getValues().map(r => ({
    date: fmtDate_(r[0]),
    studentId: normalizeId_(r[1]),
    present: String(r[2]).toLowerCase() === 'true' || r[2] === 1 || r[2] === true,
  }));
}

// ─────────────────────────────────────────────────────────────────────────
// STUDENT ENRICHMENT — builds full student object with derived analytics
// ─────────────────────────────────────────────────────────────────────────

function enrichStudents_(ss) {
  const students = readStudents_(ss);
  syncStudentsFromForm(ss); // ensure any new form-submitters are in the master
  const finalStudents = readStudents_(ss);

  const formSh = ss.getSheetByName(CONFIG.FORM_RESPONSES_SHEET);
  const responses = readForm_(formSh);
  const mcq = readMcq_(ss);
  const attendance = readAttendance_(ss);
  const notes = readNotes_(ss);

  const days = trackerWindow_(); // last N days, oldest → newest, yyyy-MM-dd strings

  return finalStudents.map(s => {
    const myResponses = responses.filter(r => r.studentId === s.id);
    const myMcq = mcq.filter(m => m.studentId === s.id);
    const myAttendance = attendance.filter(a => a.studentId === s.id);
    const myNotes = notes.filter(n => n.studentId === s.id).sort((a, b) => (b.date > a.date ? 1 : -1));

    // Daily tracker (last N days)
    const tracker = days.map(d => {
      const dayRes = myResponses.filter(r => r.date === d);
      const totalHours = dayRes.reduce((a, x) => a + x.hours, 0);
      const dayMcq = myMcq.filter(m => m.date === d);
      const mcqCount = dayMcq.reduce((a, x) => a + x.mcqCount, 0);
      const mcqAcc = dayMcq.length ? Math.round(dayMcq.reduce((a, x) => a + x.mcqAccuracy, 0) / dayMcq.length) : 0;
      return {
        date: d,
        submitted: dayRes.length > 0,
        hours: round1_(totalHours),
        mcqCount,
        mcqAccuracy: mcqAcc,
      };
    });

    // Weekly (last 7 days grouped by weekday label)
    const last7 = tracker.slice(-7);
    const weekly = last7.map(t => ({
      day: dayLabel_(t.date),
      hours: t.hours,
      mcq: t.mcqAccuracy,
    }));

    // Monthly — last 4 weeks, aggregated
    const monthly = aggregateMonthly_(tracker.length ? tracker : []);

    // Metrics
    const submittedCount = tracker.filter(t => t.submitted).length;
    const submissionRate = tracker.length ? Math.round((submittedCount / tracker.length) * 100) : 0;

    // Attendance % — from Attendance tab in window, or fallback to submissionRate
    const attWindow = myAttendance.filter(a => days.indexOf(a.date) >= 0);
    const attRate = attWindow.length
      ? Math.round((attWindow.filter(a => a.present).length / days.length) * 100)
      : submissionRate;

    // MCQ % — average from MCQ tab in window
    const mcqWindow = myMcq.filter(m => days.indexOf(m.date) >= 0);
    const mcqAccuracy = mcqWindow.length
      ? Math.round(mcqWindow.reduce((a, x) => a + x.mcqAccuracy, 0) / mcqWindow.length)
      : 0;

    // Study hours / day (average over last 7 submitted days)
    const submitted7 = last7.filter(t => t.submitted);
    const avgHours = submitted7.length ? round1_(submitted7.reduce((a, x) => a + x.hours, 0) / submitted7.length) : 0;

    // Risk assessment
    let risk = 'Healthy';
    if (attRate < 70 || (mcqAccuracy && mcqAccuracy < 60)) risk = 'At Risk';
    else if (attRate < 80) risk = 'Watch';

    // Status
    const lastSubmitted = tracker.slice(-3).some(t => t.submitted);
    const status = risk === 'At Risk' ? 'At Risk' : (lastSubmitted ? 'Active' : 'Inactive');

    return Object.assign({}, s, {
      attendance: attRate,
      studyHours: avgHours,
      mcqAccuracy,
      submissionRate,
      risk,
      status,
      weekly,
      monthly,
      tracker,
      mentorNotes: myNotes.map(n => ({ date: n.date, note: n.note })),
    });
  });
}

function aggregateMonthly_(tracker) {
  // Bucket the last 28 days into 4 weeks
  const last28 = tracker.slice(-28);
  const buckets = [[], [], [], []];
  last28.forEach((t, i) => {
    const b = Math.floor(i / 7);
    if (b < 4) buckets[b].push(t);
  });
  return buckets.map((b, i) => {
    if (!b.length) return { week: 'Week ' + (i + 1), attendance: 0, mcq: 0, hours: 0 };
    const submitted = b.filter(x => x.submitted).length;
    const attendance = Math.round((submitted / b.length) * 100);
    const mcqDays = b.filter(x => x.mcqAccuracy > 0);
    const mcq = mcqDays.length ? Math.round(mcqDays.reduce((a, x) => a + x.mcqAccuracy, 0) / mcqDays.length) : 0;
    const hours = round1_(b.reduce((a, x) => a + x.hours, 0));
    return { week: 'Week ' + (i + 1), attendance, mcq, hours };
  });
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Students
// ─────────────────────────────────────────────────────────────────────────

function listStudents(ss) {
  return enrichStudents_(ss);
}

function getStudent(ss, id) {
  const list = enrichStudents_(ss);
  return list.find(s => s.id === String(id).trim()) || null;
}

function options_() {
  return {
    batchOptions: ['All Batches', 'Super 30', 'Super 11', 'Last 15 Days', 'Last 40 Days'],
    attemptOptions: ['All Attempts', 'Sept 2026'],
    groupOptions: ['All Groups', 'Group 1', 'Group 2', 'Both Groups'],
    statusOptions: ['All Status', 'Active', 'Inactive', 'At Risk'],
  };
}

function readNotes_(ss) {
  const sh = ss.getSheetByName(CONFIG.MENTOR_NOTES_SHEET);
  if (sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, 4).getValues().map(r => ({
    id: String(r[0]),
    studentId: normalizeId_(r[1]),
    date: fmtDate_(r[2]) || fmtDate_(new Date()),
    note: String(r[3] || ''),
  }));
}

function addNote(ss, studentId, note) {
  const sh = ss.getSheetByName(CONFIG.MENTOR_NOTES_SHEET);
  const id = 'NOTE-' + Utilities.getUuid().slice(0, 8);
  const date = fmtDate_(new Date());
  sh.appendRow([id, normalizeId_(studentId), date, String(note || '')]);
  const notes = readNotes_(ss)
    .filter(n => n.studentId === normalizeId_(studentId))
    .sort((a, b) => (b.date > a.date ? 1 : -1))
    .map(n => ({ date: n.date, note: n.note }));
  return { ok: true, notes };
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Dashboard
// ─────────────────────────────────────────────────────────────────────────

function kpis(ss) {
  const list = enrichStudents_(ss);
  const total = list.length;
  const active = list.filter(s => s.status === 'Active').length;
  const atRisk = list.filter(s => s.risk === 'At Risk').length;
  const today = fmtDate_(new Date());
  const pending = list.filter(s => {
    const t = s.tracker[s.tracker.length - 1];
    return !t || !t.submitted || t.date !== today ? true : false;
  }).length;
  const avgHours = total ? round1_(list.reduce((a, s) => a + s.studyHours, 0) / total) : 0;
  const avgAttendance = total ? Math.round(list.reduce((a, s) => a + s.attendance, 0) / total) : 0;
  const avgMcq = total ? Math.round(list.reduce((a, s) => a + s.mcqAccuracy, 0) / total) : 0;
  const weeklySub = total ? Math.round(list.reduce((a, s) => a + s.submissionRate, 0) / total) : 0;
  return { total, active, atRisk, pending, avgHours, avgAttendance, avgMcq, weeklySub };
}

function recentActivity(ss) {
  const formSh = ss.getSheetByName(CONFIG.FORM_RESPONSES_SHEET);
  const responses = readForm_(formSh).sort((a, b) => (b.timestamp > a.timestamp ? 1 : -1));
  const students = readStudents_(ss);
  const nameOf = id => (students.find(s => s.id === id) || {}).name || displayNameFromId_(id);
  return responses.slice(0, 6).map((r, i) => ({
    id: i + 1,
    type: 'submission',
    student: nameOf(r.studentId),
    action: `submitted daily tracker (${r.hours}h · ${r.studied.substring(0, 40)})`,
    time: timeAgo_(r.timestamp),
    avatar: i,
  }));
}

function weeklyStudy(ss) {
  const list = enrichStudents_(ss);
  const days = trackerWindow_().slice(-7);
  return days.map(d => {
    const hoursTotal = list.reduce((a, s) => {
      const t = s.tracker.find(x => x.date === d);
      return a + (t ? t.hours : 0);
    }, 0);
    const submittedCount = list.reduce((a, s) => a + ((s.tracker.find(x => x.date === d) || {}).submitted ? 1 : 0), 0);
    const avg = submittedCount ? round1_(hoursTotal / submittedCount) : 0;
    return { day: dayLabel_(d), hours: avg, target: 7 };
  });
}

function attendanceTrend(ss) {
  const list = enrichStudents_(ss);
  const weeks = 8;
  const days = trackerWindow_(weeks * 7);
  return Array.from({ length: weeks }).map((_, i) => {
    const slice = days.slice(i * 7, (i + 1) * 7);
    if (!slice.length) return { week: 'W' + (i + 1), attendance: 0 };
    const total = list.length * slice.length;
    let submitted = 0;
    list.forEach(s => {
      slice.forEach(d => {
        const t = s.tracker.find(x => x.date === d);
        if (t && t.submitted) submitted++;
      });
    });
    return { week: 'W' + (i + 1), attendance: total ? Math.round((submitted / total) * 100) : 0 };
  });
}

function performanceMix(ss) {
  const list = enrichStudents_(ss);
  const buckets = { Excellent: 0, Good: 0, Average: 0, 'At Risk': 0 };
  list.forEach(s => {
    if (s.risk === 'At Risk') buckets['At Risk']++;
    else if (s.attendance >= 90) buckets.Excellent++;
    else if (s.attendance >= 80) buckets.Good++;
    else buckets.Average++;
  });
  return [
    { name: 'Excellent', value: buckets.Excellent, color: '#10B981' },
    { name: 'Good', value: buckets.Good, color: '#2563EB' },
    { name: 'Average', value: buckets.Average, color: '#F59E0B' },
    { name: 'At Risk', value: buckets['At Risk'], color: '#EF4444' },
  ];
}

function batchOverview(ss) {
  const list = enrichStudents_(ss);
  const groups = {};
  list.forEach(s => {
    const b = s.batch || CONFIG.DEFAULT_BATCH;
    if (!groups[b]) groups[b] = { name: b, students: 0, attSum: 0, mcqSum: 0 };
    groups[b].students++;
    groups[b].attSum += s.attendance;
    groups[b].mcqSum += s.mcqAccuracy;
  });
  return Object.values(groups).map(g => ({
    name: g.name,
    students: g.students,
    attendance: Math.round(g.attSum / g.students),
    mcq: Math.round(g.mcqSum / g.students),
  }));
}

function upcomingTasks(ss) {
  // Derived from at-risk students + today's pending submissions.
  const list = enrichStudents_(ss);
  const today = fmtDate_(new Date());
  const atRisk = list.filter(s => s.risk === 'At Risk').length;
  const pending = list.filter(s => {
    const t = s.tracker[s.tracker.length - 1];
    return !t || !t.submitted || t.date !== today;
  }).length;
  const tasks = [];
  if (pending) tasks.push({ id: 1, title: `Follow up on ${pending} pending daily tracker submissions`, due: 'Today', priority: 'high' });
  if (atRisk) tasks.push({ id: 2, title: `Schedule 1:1 with ${atRisk} at-risk students`, due: 'This week', priority: 'high' });
  tasks.push({ id: 3, title: 'Publish weekly review summary', due: 'Fri, 6:00 PM', priority: 'medium' });
  tasks.push({ id: 4, title: 'Update mock test question bank', due: 'Next week', priority: 'low' });
  return tasks;
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Daily Tracker
// ─────────────────────────────────────────────────────────────────────────

function trackerDay(ss, dayIndex, batch) {
  const list = enrichStudents_(ss);
  const days = trackerWindow_();
  const idx = Math.max(0, Math.min(days.length - 1, dayIndex == null ? days.length - 1 : dayIndex));
  const filtered = list.filter(s => !batch || batch === 'All Batches' || s.batch === batch);
  const dayRows = filtered.map(s => ({
    id: s.id,
    name: s.name,
    avatar: s.avatar,
    batch: s.batch,
    entry: s.tracker[idx] || { date: days[idx], submitted: false, hours: 0, mcqCount: 0, mcqAccuracy: 0 },
  }));
  const submitted = dayRows.filter(x => x.entry.submitted).length;
  const missed = dayRows.length - submitted;
  const rate = dayRows.length ? Math.round((submitted / dayRows.length) * 100) : 0;
  return { list: dayRows, submitted, missed, rate, days };
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Leaderboard
// ─────────────────────────────────────────────────────────────────────────

function leaderboard(ss, mode) {
  const list = enrichStudents_(ss);
  return list.map(s => Object.assign({}, s, { score: scoreFor_(s, mode) }))
    .sort((a, b) => b.score - a.score);
}

function scoreFor_(s, mode) {
  if (mode === 'weekly') {
    const avgH = s.weekly.length ? s.weekly.reduce((a, w) => a + w.hours, 0) / s.weekly.length : 0;
    const avgM = s.weekly.length ? s.weekly.reduce((a, w) => a + w.mcq, 0) / s.weekly.length : 0;
    return Math.round(avgH * 5 + avgM);
  }
  if (mode === 'monthly') {
    const avgA = s.monthly.length ? s.monthly.reduce((a, m) => a + m.attendance, 0) / s.monthly.length : 0;
    const avgM = s.monthly.length ? s.monthly.reduce((a, m) => a + m.mcq, 0) / s.monthly.length : 0;
    return Math.round((avgA + avgM) / 2);
  }
  return Math.round((s.attendance + s.mcqAccuracy + s.submissionRate) / 3);
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Announcements
// ─────────────────────────────────────────────────────────────────────────

function listAnnouncements(ss) {
  const sh = ss.getSheetByName(CONFIG.ANNOUNCEMENTS_SHEET);
  if (sh.getLastRow() < 2) return [];
  return sh.getRange(2, 1, sh.getLastRow() - 1, 7).getValues().map(r => ({
    id: String(r[0]),
    title: String(r[1]),
    body: String(r[2]),
    audience: String(r[3]),
    date: fmtDate_(r[4]) || String(r[4]),
    pinned: r[5] === true || String(r[5]).toLowerCase() === 'true',
    author: String(r[6]),
  })).sort((a, b) => (b.date > a.date ? 1 : -1));
}

function createAnnouncement(ss, payload) {
  const sh = ss.getSheetByName(CONFIG.ANNOUNCEMENTS_SHEET);
  const id = 'ANN-' + Utilities.getUuid().slice(0, 6).toUpperCase();
  const mentor = getMentor(ss);
  const row = [
    id,
    String(payload.title || '').trim(),
    String(payload.body || '').trim(),
    String(payload.audience || 'All Batches'),
    fmtDate_(new Date()),
    false,
    mentor.name || 'Ujjwal Pathak',
  ];
  sh.appendRow(row);
  return {
    id: row[0], title: row[1], body: row[2], audience: row[3],
    date: row[4], pinned: false, author: row[6],
  };
}

function togglePinAnnouncement(ss, id) {
  const sh = ss.getSheetByName(CONFIG.ANNOUNCEMENTS_SHEET);
  const values = sh.getRange(2, 1, sh.getLastRow() - 1, 7).getValues();
  for (let i = 0; i < values.length; i++) {
    if (String(values[i][0]) === String(id)) {
      const current = values[i][5] === true || String(values[i][5]).toLowerCase() === 'true';
      sh.getRange(i + 2, 6).setValue(!current);
      return { ok: true };
    }
  }
  return { ok: false };
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Reports
// ─────────────────────────────────────────────────────────────────────────

function studentReport(ss) {
  const list = enrichStudents_(ss);
  return list.map(s => ({
    id: s.id, name: s.name, avatar: s.avatar, batch: s.batch,
    attendance: s.attendance, studyHours: s.studyHours,
    mcqAccuracy: s.mcqAccuracy, submissionRate: s.submissionRate,
  }));
}

// ─────────────────────────────────────────────────────────────────────────
// ACTIONS — Mentor / Notifications
// ─────────────────────────────────────────────────────────────────────────

function getMentor(ss) {
  const sh = ss.getSheetByName(CONFIG.MENTOR_SHEET);
  const out = {};
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 2).getValues().forEach(r => { out[String(r[0])] = String(r[1]); });
  }
  return {
    name: out.name || 'Ujjwal Pathak',
    email: out.email || '',
    avatar: out.avatar || '',
  };
}

function updateMentor(ss, payload) {
  const sh = ss.getSheetByName(CONFIG.MENTOR_SHEET);
  const data = sh.getRange(2, 1, Math.max(1, sh.getLastRow() - 1), 2).getValues();
  const map = {};
  data.forEach((r, i) => { if (r[0]) map[String(r[0])] = i + 2; });
  Object.keys(payload).forEach(k => {
    if (map[k]) sh.getRange(map[k], 2).setValue(payload[k]);
    else sh.appendRow([k, payload[k]]);
  });
  return getMentor(ss);
}

function getNotifications(ss) {
  const sh = ss.getSheetByName(CONFIG.NOTIFICATIONS_SHEET);
  const out = {};
  if (sh.getLastRow() > 1) {
    sh.getRange(2, 1, sh.getLastRow() - 1, 2).getValues().forEach(r => {
      out[String(r[0])] = String(r[1]).toLowerCase() === 'true';
    });
  }
  return {
    emailNotif: out.emailNotif !== false,
    smsNotif: !!out.smsNotif,
    dailyDigest: out.dailyDigest !== false,
  };
}

function updateNotifications(ss, payload) {
  const sh = ss.getSheetByName(CONFIG.NOTIFICATIONS_SHEET);
  const data = sh.getRange(2, 1, Math.max(1, sh.getLastRow() - 1), 2).getValues();
  const map = {};
  data.forEach((r, i) => { if (r[0]) map[String(r[0])] = i + 2; });
  Object.keys(payload).forEach(k => {
    if (map[k]) sh.getRange(map[k], 2).setValue(payload[k] ? 'true' : 'false');
    else sh.appendRow([k, payload[k] ? 'true' : 'false']);
  });
  return getNotifications(ss);
}

// ─────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────

function normalizeId_(raw) {
  let s = String(raw || '').trim().toUpperCase();
  if (!s) return '';
  // Strip repeated ID pattern like "UMP0004UMP0004" → "UMP0004"
  const dup = s.match(/^(UMP\d+)\1+$/);
  if (dup) s = dup[1];
  // Pad numeric portion of UMP\d+ to 4 digits (UMP002 → UMP0002)
  const m = s.match(/^UMP(\d+)$/);
  if (m) {
    let n = m[1];
    while (n.length < 4) n = '0' + n;
    return 'UMP' + n;
  }
  return s;
}

function displayNameFromId_(id) {
  const s = String(id || '').trim();
  if (!s) return 'Student';
  if (/^UMP\d+$/i.test(s)) return 'Student ' + s.toUpperCase();
  return s;
}

function parseHours_(v) {
  if (v === '' || v == null) return 0;
  const n = parseFloat(v);
  if (isNaN(n)) return 0;
  return round1_(n);
}

function parseDate_(v) {
  if (!v) return '';
  if (v instanceof Date) return fmtDate_(v);
  const s = String(v).trim();
  // Try DD/MM/YYYY
  const m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (m) {
    const d = new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
    return fmtDate_(d);
  }
  // Try YYYY-MM-DD
  const m2 = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m2) return `${m2[1]}-${m2[2]}-${m2[3]}`;
  const d = new Date(s);
  if (!isNaN(d.getTime())) return fmtDate_(d);
  return '';
}

function fmtDate_(v) {
  if (!v) return '';
  const d = v instanceof Date ? v : new Date(v);
  if (isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function dayLabel_(dateStr) {
  const d = new Date(dateStr);
  return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
}

function trackerWindow_(days) {
  const N = days || CONFIG.TRACKER_DAYS;
  const out = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = N - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    out.push(fmtDate_(d));
  }
  return out;
}

function round1_(n) {
  return Math.round(Number(n) * 10) / 10;
}

function timeAgo_(date) {
  if (!date) return '';
  const d = date instanceof Date ? date : new Date(date);
  if (isNaN(d.getTime())) return '';
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
  if (diff < 86400) return Math.floor(diff / 3600) + ' hr ago';
  const days = Math.floor(diff / 86400);
  return days === 1 ? '1 day ago' : days + ' days ago';
}
