/**
 * Mentor Dashboard — All screen definitions.
 * Each screen is a function returning HTML via the page() pattern.
 * Uses real API data (LIVEDATA loaded by app.js) + SVG charts (charts.js).
 */
"use strict";

const C = window.UMP_CHARTS || {};

/* ===================== DASHBOARD ===================== */
function sDash() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const today = LIVEDATA.tracker || {};
  const tests = LIVEDATA.tests || [];
  const msgs = LIVEDATA.messages || [];
  const sum = today.summary || {};
  const need = stu.filter((s) => s.today && s.today.status === "missed" || s.access === false);

  // Build attendance trend (last 7 days from tracker)
  const days = (today.days || []).slice(-7);
  const attData = days.map((d) => ({ label: d.slice(5), value: 0 })); // placeholder

  // Build batch overview from students
  const batchMap = {};
  stu.forEach((s) => {
    if (!batchMap[s.batch]) batchMap[s.batch] = { label: s.batch, value: 0 };
    batchMap[s.batch].value++;
  });
  const batchData = Object.values(batchMap);

  // Performance mix (by band)
  const bandMap = {};
  stu.forEach((s) => {
    const b = band(s)[0];
    bandMap[b] = (bandMap[b] || 0) + 1;
  });
  const perfData = Object.keys(bandMap).map((k) => ({ label: k, value: bandMap[k] }));

  const kpis = [
    ["Active students", stu.length, "#111827"],
    ["Test submissions", tests.length, "#111827"],
    ["Messages", msgs.length, msgs.filter((m) => m.unread).length > 0 ? "#DC2626" : "#111827"],
    ["Need action", need.length, need.length > 0 ? "#DC2626" : "#16A34A"],
  ];

  return page({
    eyebrow: new Date().toLocaleDateString("en-IN", { weekday: "long", day: "2-digit", month: "short", year: "numeric" }),
    title: "Dashboard",
    desc: "One screen for what needs you tonight. Everything else is a click away.",
    stats: kpis,
    body:
      '<div class="tb"><strong style="font-size:13px">Needs attention tonight</strong><span class="pl" style="margin-left:auto">' + need.length + ' students</span></div>' +
      rowsHtml(["Student", "Batch", "Group", "Why", ""],
        need.slice(0, 12).map((s) =>
          cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) + cell(reasonChips(s)) + cell('<button class="b bg2 xs" onclick="openStudent(\'' + s.id + '\')">Open</button>', "right")
        ).join(""),
        "Nothing needs attention — everything is on track."
      ) +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px">' +
        '<div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Students by batch</h3>' + C.barChart(batchData, { height: 160, showValues: true }) + '</div>' +
        '<div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Performance mix</h3>' + C.doughnutChart(perfData, { size: 140 }) + '</div>' +
      '</div>',
  });
}

/* ===================== BATCHES & GROUPS ===================== */
function sBatches() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const batchMap = {};
  stu.forEach((s) => {
    if (!batchMap[s.batch]) batchMap[s.batch] = { "Group 1": 0, "Group 2": 0, "Both": 0, total: 0 };
    if (batchMap[s.batch][s.group] != null) batchMap[s.batch][s.group]++;
    batchMap[s.batch].total++;
  });
  const rows = Object.keys(batchMap).sort().map((b) =>
    cell('<strong style="font-size:12.5px">' + esc(b) + '</strong>') +
    cell(batchMap[b]["Group 1"], "tn") + cell(batchMap[b]["Group 2"], "tn") + cell(batchMap[b]["Both"], "tn") +
    cell('<strong>' + batchMap[b].total + '</strong>', "tn") +
    cell('<button class="b bg2 xs" onclick="S.filters.batch=\'' + b + '\';go(\'students\')">View</button>', "right")
  ).join("");
  return page({
    eyebrow: "Structure", title: "Batches & groups",
    desc: "Active cohorts with real-time student counts.",
    body: rowsHtml(["Batch", "Group 1", "Group 2", "Both", "Total", ""], rows, "No active batches"),
  });
}

/* ===================== STUDENTS ===================== */
function sStudents() {
  return listScreen({
    key: "students", title: "Students", eyebrow: "People",
    desc: "All enrolled students, live roster.",
    searchable: true, searchText: (s) => s.name + " " + s.id + " " + (s.batch || "") + " " + (s.group || ""),
    rows: () => (LIVEDATA.students || []).filter((s) => !s.archived),
    cols: ["Student", "Batch", "Group", "Status", ""],
    render: (rows) => rows.map((s) =>
      cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) +
      cell('<span class="tag ' + band(s)[1] + '">' + band(s)[0] + '</span>') +
      cell('<button class="b bg2 xs" onclick="openStudent(\'' + s.id + '\')">Open</button>', "right")
    ).join(""),
    empty: "No students match this filter",
    actions: [{ label: "Export CSV", fn: "exportCsv()", icon: "dl" }],
  });
}

function exportCsv() {
  const rows = (LIVEDATA.students || []).filter((s) => !s.archived);
  const csv = ["Student ID,Name,Batch,Group,Status"];
  rows.forEach((s) => { csv.push([s.id, s.name, s.batch, s.group, band(s)[0]].map((v) => '"' + (v || "").replace(/"/g, '""') + '"').join(",")); });
  const blob = new Blob([csv.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "students.csv"; a.click();
  URL.revokeObjectURL(url);
  toast("Exported " + rows.length + " students");
}

/* ===================== STUDENT DRAWER ===================== */
function openStudent(id) {
  S.drawer = id;
  const s = (LIVEDATA.students || []).find((x) => x.id === id);
  if (!s) { toast("Student not found"); return; }
  const tests = s.tests || [];
  const d = s.today || {};
  document.getElementById("dh").innerHTML =
    '<span class="av" style="width:42px;height:42px;font-size:14px">' + ini(s.name) + '</span>' +
    '<div style="flex:1;min-width:0"><div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><strong style="font-size:15.5px">' + esc(s.name) + '</strong>' + gchip(s.group) + '</div>' +
    '<div class="fa" style="font-size:11.5px;margin-top:2px">' + s.id + ' · ' + esc(s.batch || "—") + '</div>' +
    '<div style="display:flex;gap:5px;margin-top:6px;flex-wrap:wrap">' +
    (s.access === false ? '<span class="chip rd">No app access</span>' : '') +
    '<span class="tag ' + band(s)[1] + '">' + band(s)[0] + '</span></div></div>' +
    '<button class="b bg2 xs" onclick="S.drawer=null;draw()">' + ic("close", 14) + '</button>';

  const tabs = [["ov", "Overview"], ["work", "Work"], ["tests", "Tests"]];
  const cur = S.dtab.id === id ? (S.dtab.t || "ov") : "ov";
  document.getElementById("dtabs").innerHTML = tabs.map((t) =>
    '<button class="tab ' + (cur === t[0] ? "on" : "") + '" onclick="S.dtab={id:\'' + id + '\',t:\'' + t[0] + '\'};openStudent(\'' + id + '\')">' + t[1] + '</button>'
  ).join("");

  let body = "";
  if (cur === "ov") {
    body =
      (d.submitted ? '<div class="card" style="padding:12px"><strong style="font-size:13px">Submitted · ' + (d.hours || 0) + ' hours</strong><div class="fa" style="font-size:11.5px;margin-top:2px">' + esc(d.subjects || "") + '</div></div>'
        : '<div class="card" style="padding:12px;border-color:#FCA5A5;background:#FEF2F2"><strong style="font-size:13px;color:#B91C1C">Not submitted today</strong></div>') +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">' +
      '<div class="card" style="padding:10px"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Streak</div><div style="font-size:18px;font-weight:600">' + (s.streak || 0) + ' days</div></div>' +
      '<div class="card" style="padding:10px"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Total hours</div><div style="font-size:18px;font-weight:600">' + (s.totalHours || 0) + ' h</div></div>' +
      '<div class="card" style="padding:10px"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Attendance</div><div style="font-size:18px;font-weight:600">' + (s.lb ? (s.lb.attendance || 0) + "%" : "—") + '</div></div>' +
      '<div class="card" style="padding:10px"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Rank</div><div style="font-size:18px;font-weight:600">' + (s.lb && s.lb.rank ? "#" + s.lb.rank : "—") + '</div></div>' +
      '</div>';
  } else if (cur === "work") {
    const tg = LIVEDATA.targets || [];
    const studentTargets = tg.filter((t) => t.studentCount > 0).slice(0, 8);
    body = studentTargets.length ? studentTargets.map((x) =>
      '<div class="card" style="padding:10px;margin-bottom:7px"><div style="font-size:12.5px;font-weight:600">' + esc(x.subject || "") + '</div><div class="fa" style="font-size:11px">' + esc(x.batch || "") + ' · ' + gchip(x.group) + '</div></div>'
    ).join("") : '<div class="empty">No targets found</div>';
  } else if (cur === "tests") {
    body = tests.length ? rowsHtml(["Test", "Subject", "Score", "Date", "Remarks"],
      tests.map((t) =>
        cell('<span style="font-size:11.5px">' + esc((t.title || "").slice(0, 40)) + '</span>') +
        cell('<span class="chip gy">' + esc(t.subject || "—") + '</span>') +
        cell('<strong class="tn">' + (t.score == null ? "—" : t.score + "%") + '</strong>') +
        cell(fd(t.at), "tn fa") +
        cell('<span class="fa" style="font-size:11px">' + esc((t.remarks || "").slice(0, 50)) + '</span>')
      ).join(""), "No tests submitted") : '<div class="empty">No tests submitted</div>';
  }
  document.getElementById("db").innerHTML = body;
}

/* ===================== DAILY TRACKER ===================== */
function sTracker() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const cur = S.tab.tracker || "all";
  const tabs = [["all", "All", stu.length], ["sub", "Submitted", stu.filter((s) => s.today && s.today.submitted).length], ["miss", "Missed", stu.filter((s) => s.today && s.today.status === "missed").length]];
  const filtered = cur === "all" ? stu : stu.filter((s) => s.today && (cur === "sub" ? s.today.submitted : s.today.status === "missed"));
  const submitted = stu.filter((s) => s.today && s.today.submitted).length;
  const rate = stu.length ? Math.round((submitted / stu.length) * 100) : 0;

  return page({
    eyebrow: "Engagement", title: "Daily Tracker",
    desc: "Track daily submissions across batches.",
    stats: [["Roster", stu.length], ["Submitted", submitted], ["Rate", rate + "%"]],
    tabs: tabs, tab: cur, key: "tracker",
    body: rowsHtml(["Student", "Batch", "Group", "Today", "Status", ""],
      filtered.map((s) =>
        cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) +
        cell(s.today && s.today.submitted ? '<span class="tag g">Submitted</span>' : s.today && s.today.status === "missed" ? '<span class="tag r">Missed</span>' : '<span class="tag n">—</span>') +
        cell(s.today ? esc(s.today.hours || 0) + "h" : "—", "tn") +
        cell('<button class="b bg2 xs" onclick="openStudent(\'' + s.id + '\')">Open</button>', "right")
      ).join(""),
      "Nothing in this tab"
    ),
  });
}

/* ===================== DAILY TARGETS ===================== */
function sTargets() {
  const tg = LIVEDATA.targets || [];
  const cur = S.tab.targets || "Group 1";
  const tabs = TRACKS.map((g) => [g, g, tg.filter((t) => (t.group || "").replace("Groups", "Group") === g).length]);
  const filtered = tg.filter((t) => (t.group || "").replace("Groups", "Group") === cur);

  return listScreen({
    key: "targets", title: "Daily Targets", eyebrow: "Publish",
    desc: "Plans are tracked per group, never per batch.",
    tabs: tabs, tab: cur, key2: "targets",
    rows: () => filtered,
    rowsForTab: (cur2, rows) => rows.filter((t) => (t.group || "").replace("Groups", "Group") === cur2),
    cols: ["Dates", "Subject", "Attempt", "Tasks", "Students", ""],
    render: (rows) => rows.map((t) =>
      cell(fd(t.startDate) + " → " + fd(t.endDate), "tn") +
      cell('<strong style="font-size:12px">' + esc(t.subject || "—") + '</strong>') +
      cell('<span class="fa">' + esc(t.attempt || "—") + '</span>') +
      cell('<span class="fa" style="font-size:11.5px">' + esc((t.tasks || []).slice(0, 2).join(" · ")) + '</span>') +
      cell(t.studentCount || 0, "tn") +
      cell('<button class="b bg2 xs" onclick="openTarget(\'' + t.id + '\')">View</button>', "right")
    ).join(""),
    empty: "No targets for this group",
    actions: [{ label: "Add target", fn: "openTargetModal()", icon: "plus", primary: true }],
  });
}

function openTarget(id) {
  const t = (LIVEDATA.targets || []).find((x) => x.id === id);
  if (!t) return;
  openModal(
    '<p class="eyebrow">Target plan</p><h2 style="margin:6px 0 10px;font-size:17px">' + esc(t.subject) + ' · ' + esc(t.attempt || "") + '</h2>' +
    '<div class="kv"><span>Dates</span><b>' + fd(t.startDate) + ' → ' + fd(t.endDate) + '</b><span>Batch</span><b>' + esc(t.batch || "") + '</b><span>Group</span><b>' + esc(t.group || "") + '</b><span>Students</span><b>' + (t.studentCount || 0) + '</b></div>' +
    '<div style="margin-top:12px;border:1px solid #E5E7EB;border-radius:9px;padding:9px 11px">' + ((t.tasks || []).map((x) => '<div style="font-size:12px;padding:3px 0">• ' + esc(x) + '</div>').join("") || '<span class="fa">No tasks</span>') + '</div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Close</button></div>'
  );
}

function openTargetModal() {
  openModal(
    '<p class="eyebrow">New daily target</p><h2 style="margin:6px 0 10px;font-size:17px">Publish a target</h2>' +
    '<div class="f"><label>Subject</label><input id="nt-subject" placeholder="e.g. Costing"/></div>' +
    '<div class="f"><label>Tasks (one per line)</label><textarea id="nt-tasks" rows="4" placeholder="Task 1&#10;Task 2&#10;Task 3" style="width:100%;border:1px solid #E5E7EB;border-radius:8px;padding:9px;font:inherit;font-size:12.5px;resize:none"></textarea></div>' +
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px"><div class="f"><label>Group</label><select id="nt-group"><option>Group 1</option><option>Group 2</option><option>Both</option></select></div><div class="f"><label>Batch</label><select id="nt-batch"><option>All</option></select></div></div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Cancel</button><button class="b bp sm" onclick="saveTarget()">Publish</button></div>'
  );
}

async function saveTarget() {
  const subject = document.getElementById("nt-subject").value.trim();
  const tasks = document.getElementById("nt-tasks").value.split("\n").filter(Boolean);
  const group = document.getElementById("nt-group").value;
  if (!subject || !tasks.length) { toast("Subject and at least one task required"); return; }
  try {
    const res = await api("/targets", { method: "POST", body: JSON.stringify({ subject, tasks, group }) });
    toast("Target published");
    closeModal();
    LIVEDATA.targets = LIVEDATA.targets || [];
    LIVEDATA.targets.push(res.target || res);
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== TARGET PLANS ===================== */
function sPlans() {
  const tg = LIVEDATA.targets || [];
  return page({
    eyebrow: "Planning", title: "Target Plans",
    desc: "Published plans from the API, by group and batch.",
    stats: [["Plans", tg.length], ["Groups", 3], ["Batches", 4]],
    body: rowsHtml(["Dates", "Subject", "Group", "Batch", "Tasks", "Students"],
      tg.slice(0, 60).map((t) =>
        cell(fd(t.startDate) + " → " + fd(t.endDate), "tn") +
        cell(esc(t.subject || "")) + cell(gchip((t.group || "").replace("Groups", "Group"))) +
        cell('<span class="fa">' + esc(t.batch || "") + '</span>') +
        cell((t.tasks || []).length, "tn") + cell(t.studentCount || 0, "tn")
      ).join(""), "No plans"
    ),
  });
}

/* ===================== COVERAGE ===================== */
function sCoverage() {
  const tg = LIVEDATA.targets || [];
  const days = (LIVEDATA.tracker && LIVEDATA.tracker.days) || [];
  if (!days.length) {
    // Generate last 14 days
    const today = new Date();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(today); d.setDate(d.getDate() - i);
      days.push(d.toISOString().slice(0, 10));
    }
  }
  const body = '<div style="overflow:auto"><table style="font-size:11px"><thead><tr><th>Group</th>' +
    days.map((d) => '<th class="tn" style="writing-mode:vertical-rl;font-size:9.5px;padding:4px 2px">' + d.slice(5) + '</th>').join("") + '</tr></thead><tbody>' +
    TRACKS.map((g) => '<tr><td style="font-weight:600">' + g + '</td>' + days.map((d) => {
      const hit = tg.some((t) => (t.group || "").replace("Groups", "Group") === g && t.startDate <= d && t.endDate >= d);
      return '<td style="padding:2px"><div style="width:17px;height:17px;border-radius:4px;background:' + (hit ? "#16A34A" : "#FEE2E2") + '" title="' + d + '"></div></td>';
    }).join("") + '</tr>').join("") +
    '</tbody></table></div><div class="nl2">Green = a plan covers that day. Red = students open the app to an empty list.</div>';
  return page({ eyebrow: "Planning", title: "Coverage", desc: "Which group has a published target on which day.", body: body });
}

/* ===================== START DATES ===================== */
function sStartdates() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const sorted = stu.slice().sort((a, b) => (a.today && a.today.start || "").localeCompare(b.today && b.today.start || ""));
  return page({
    eyebrow: "Planning", title: "Start Dates",
    desc: "When each student's tracker journey begins.",
    body: rowsHtml(["Student", "Batch", "Group", "Start", "Days active", ""],
      sorted.map((s) =>
        cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) +
        cell(fd(s.today && s.today.start), "tn fa") +
        cell(s.hist ? s.hist.expectedDays : "—", "tn") +
        cell('<button class="b bg2 xs" onclick="openStudent(\'' + s.id + '\')">Open</button>', "right")
      ).join(""), "No start dates"
    ),
  });
}

/* ===================== LEADERBOARD ===================== */
function sLeader() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived && s.lb && s.lb.rank);
  const ranked = stu.sort((a, b) => (a.lb.rank || 999) - (b.lb.rank || 999)).slice(0, 30);
  const top3 = ranked.slice(0, 3);

  const podium = top3.length ?
    '<div style="display:flex;align-items:flex-end;justify-content:center;gap:12px;padding:16px 0">' +
    (top3[1] ? '<div style="text-align:center;font-size:11px"><div class="card" style="padding:12px;height:80px;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#F3F4F6"><span class="av" style="width:36px;height:36px;font-size:12px">' + ini(top3[1].name) + '</span><strong style="font-size:11px;margin-top:4px">#2</strong></div><div class="fa" style="margin-top:4px">' + esc(top3[1].name) + '</div></div>' : '') +
    (top3[0] ? '<div style="text-align:center;font-size:11px"><div class="card" style="padding:12px;height:100px;display:flex;flex-direction:column;justify-content:center;align-items:center;border-color:#FCD34D;background:#FFFBEB">' + ic("crown", 20) + '<span class="av" style="width:40px;height:40px;font-size:13px;margin-top:4px">' + ini(top3[0].name) + '</span><strong style="font-size:12px;margin-top:4px">#1</strong></div><div><strong style="font-size:12px">' + esc(top3[0].name) + '</strong></div></div>' : '') +
    (top3[2] ? '<div style="text-align:center;font-size:11px"><div class="card" style="padding:12px;height:70px;display:flex;flex-direction:column;justify-content:center;align-items:center;background:#FEF3C7"><span class="av" style="width:34px;height:34px;font-size:11px">' + ini(top3[2].name) + '</span><strong style="font-size:10px;margin-top:4px">#3</strong></div><div class="fa" style="margin-top:4px">' + esc(top3[2].name) + '</div></div>' : '') +
    '</div>' : '<div class="empty">No ranked students yet</div>';

  const table = ranked.slice(3, 20).map((s, i) =>
    cell('#' + (i + 4), "tn") + cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') +
    cell(s.lb.score || 0, "tn") + cell(s.lb.hours || 0 + "h", "tn") + cell(s.lb.streak || 0 + "d", "tn") +
    cell('<button class="b bg2 xs" onclick="openStudent(\'' + s.id + '\')">Open</button>', "right")
  ).join("");

  return page({
    eyebrow: "Engagement", title: "Leaderboard",
    desc: "Top performers across the cohort.",
    body: podium + rowsHtml(["#", "Student", "Batch", "Score", "Hours", "Streak", ""], table, "No ranked students"),
  });
}

/* ===================== MESSAGES ===================== */
function sMessages() {
  const th = LIVEDATA.messages || [];
  const cur = S.thread || (th[0] && th[0].studentId);
  const sel = th.find((t) => t.studentId === cur);
  const stu = (LIVEDATA.students || []).find((x) => x.id === cur) || {};

  return page({
    eyebrow: "Student messages", title: "Messages",
    desc: "Real threads from the API inbox.",
    body: '<div style="display:grid;grid-template-columns:250px 1fr;min-height:380px">' +
      '<div style="border-right:1px solid #E5E7EB;max-height:480px;overflow:auto">' +
      th.map((t) => {
        const s = (LIVEDATA.students || []).find((x) => x.id === t.studentId) || {};
        return '<button onclick="S.thread=\'' + t.studentId + '\';draw()" style="display:block;width:100%;text-align:left;padding:9px 11px;border-bottom:1px solid #F3F4F6;background:' + (t.studentId === cur ? "#EEF2FF" : "#fff") + '">' +
          '<div style="display:flex;gap:7px;align-items:center"><span class="av" style="width:24px;height:24px;font-size:9.5px">' + ini(t.name || s.name || t.studentId) + '</span><div style="min-width:0"><div style="font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(t.name || s.name || t.studentId) + '</div><div class="fa" style="font-size:10px">' + esc(t.at || "") + '</div></div>' + (t.unread ? '<span class="bdg r" style="margin-left:auto">' + t.unread + '</span>' : '') + '</div></button>';
      }).join("") + '</div>' +
      '<div style="padding:14px">' + (sel ?
        '<div style="font-size:13px;font-weight:650;margin-bottom:3px">' + esc(sel.name || cur) + '</div>' +
        '<div class="fa" style="font-size:11px;margin-bottom:12px">' + cur + ' · ' + esc(stu.batch || "") + '</div>' +
        '<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:9px;padding:11px;font-size:12.5px">' + esc(sel.last || "No messages") + '</div>' +
        '<div class="fa" style="font-size:10.5px;margin-top:6px">' + (sel.from === "student" ? "From student" : "From mentor") + ' · ' + esc(sel.at || "") + '</div>' +
        '<div style="margin-top:12px"><textarea id="replybox" placeholder="Write a reply…" style="width:100%;height:74px;border:1px solid #E5E7EB;border-radius:9px;padding:9px;font:inherit;font-size:12.5px;resize:none"></textarea>' +
        '<div class="row" style="margin-top:8px;justify-content:flex-end"><button class="b bp sm" onclick="sendReply(\'' + cur + '\')">' + ic("send", 14) + ' Send reply</button></div></div>'
        : '<div class="empty"><b>Select a thread</b></div>') + '</div></div>'
  });
}

async function sendReply(studentId) {
  const el = document.getElementById("replybox");
  const txt = el && el.value.trim();
  if (!txt) { toast("Type a reply first"); return; }
  try {
    await api("/messages/reply", { method: "POST", body: JSON.stringify({ studentId, message: txt }) });
    toast("Reply sent to " + studentId);
    el.value = "";
    LIVEDATA.messages = LIVEDATA.messages || [];
    const t = LIVEDATA.messages.find((x) => x.studentId === studentId);
    if (t) { t.last = txt; t.from = "mentor"; t.at = new Date().toISOString(); }
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== TESTS ===================== */
function sTests() {
  const ent = (LIVEDATA.students || []).flatMap((s) => (s.tests || []).map((t) => ({ ...t, sid: s.id, sname: s.name, batch: s.batch, group: s.group })));
  const cur = S.tab.tests || "all";
  const tabs = [["all", "All", ent.length], ["mcq-test", "MCQ", ent.filter((t) => t.kind === "mcq-test").length], ["paper-test", "Paper", ent.filter((t) => t.kind === "paper-test").length]];
  const filtered = cur === "all" ? ent : ent.filter((t) => t.kind === cur);

  return listScreen({
    key: "tests", title: "Tests", eyebrow: "Assessments",
    desc: "Student test submissions and self-evaluation marks.",
    searchable: true, searchText: (t) => (t.sname || "") + " " + (t.sid || "") + " " + (t.title || ""),
    tabs: tabs, tab: cur,
    rows: () => filtered,
    cols: ["Student", "Test", "Subject", "Score", "Date", "Remarks"],
    render: (rows) => rows.slice(0, 80).map((t) =>
      cell(personCell({ name: t.sname, id: t.sid })) +
      cell('<span style="font-size:11.5px">' + esc((t.title || "").slice(0, 44)) + '</span>') +
      cell('<span class="chip gy">' + esc(t.subject || "—") + '</span>') +
      cell('<strong class="tn">' + (t.score == null ? "—" : t.score + "%") + '</strong>') +
      cell(fd(t.at), "tn fa") +
      cell('<span class="fa" style="font-size:11px">' + esc((t.remarks || "").slice(0, 60)) + '</span>')
    ).join(""),
    empty: "No test submissions",
  });
}

/* ===================== MCQ SCORES ===================== */
function sMcqScores() {
  const m = LIVEDATA.mcq || [];
  return page({
    eyebrow: "Practice", title: "MCQ Scores",
    desc: "Chapter-wise MCQ performance from the analytics API.",
    body: rowsHtml(["Student", "Chapter", "Attempts", "Accuracy", "Band"],
      m.slice(0, 80).map((r) =>
        cell(esc(r.studentId || r.id || "—")) +
        cell('<span class="fa">' + esc(r.chapter || r.chapterId || "—") + '</span>') +
        cell(r.attemptCount || r.attempts || 0, "tn") +
        cell(esc(r.accuracyRange || r.accuracy || "—"), "tn") +
        cell('<span class="tag ' + (/master|strong/i.test(r.masteryBand || "") ? "g" : /weak/i.test(r.masteryBand || "") ? "r" : "a") + '">' + esc(r.masteryBand || "—") + '</span>')
      ).join(""), "No MCQ score rows"
    ),
  });
}

/* ===================== NOTES ===================== */
function sNotes() {
  const n = LIVEDATA.notes || [];
  return page({
    eyebrow: "Content", title: "Notes",
    desc: "Upload and manage study notes for students.",
    body: rowsHtml(["Title", "Subject", "Category", "Date", ""],
      n.slice(0, 60).map((x) =>
        cell('<strong style="font-size:12px">' + esc((x.title || "").slice(0, 60)) + '</strong>') +
        cell('<span class="chip gy">' + esc(x.subject || "—") + '</span>') +
        cell('<span class="fa">' + esc(x.category || "—") + '</span>') +
        cell(esc(x.date || "—"), "tn fa") +
        cell('<button class="b bg2 xs" onclick="toast(\'Download: ' + esc(x.title || "") + '\')">' + ic("download", 12) + '</button>', "right")
      ).join(""), "No published notes"
    ),
    actions: [{ label: "Upload PDF", fn: "openNoteUpload()", icon: "upload", primary: true }],
  });
}

function openNoteUpload() {
  openModal(
    '<p class="eyebrow">Upload note</p><h2 style="margin:6px 0 10px;font-size:17px">Upload a study note</h2>' +
    '<div class="f"><label>Subject</label><select id="nu-subject"><option>Accounts</option><option>Law</option><option>Costing</option><option>Audit</option><option>FM</option><option>SM</option><option>GST</option><option>Taxation</option></select></div>' +
    '<div class="f"><label>Title (optional)</label><input id="nu-title" placeholder="Auto-detected from filename if blank"/></div>' +
    '<div class="f"><label>PDF file (max 20 MB)</label><input id="nu-file" type="file" accept=".pdf" style="border:1px solid #E5E7EB;border-radius:8px;padding:9px;width:100%;font-size:12.5px"/></div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Cancel</button><button class="b bp sm" onclick="uploadNote()">Upload</button></div>'
  );
}

async function uploadNote() {
  const fileInput = document.getElementById("nu-file");
  const file = fileInput.files[0];
  if (!file) { toast("Select a PDF file"); return; }
  if (file.size > 20 * 1024 * 1024) { toast("File exceeds 20 MB limit"); return; }
  const subject = document.getElementById("nu-subject").value;
  const title = document.getElementById("nu-title").value.trim() || file.name.replace(/\.pdf$/i, "");
  try {
    toast("Uploading…");
    const formData = new FormData();
    formData.append("file", file);
    formData.append("subject", subject);
    formData.append("title", title);
    const token = localStorage.getItem("ump_mentor_token");
    const res = await fetch(API_BASE + "/api/notes/create", { method: "POST", headers: { "Authorization": "Bearer " + token }, body: formData });
    if (!res.ok) throw new Error("Upload failed (" + res.status + ")");
    const data = await res.json();
    toast("Note uploaded: " + title);
    closeModal();
    LIVEDATA.notes = LIVEDATA.notes || [];
    LIVEDATA.notes.unshift({ title, subject, date: new Date().toISOString().slice(0, 10) });
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== ANNOUNCEMENTS ===================== */
function sAnnouncements() {
  const ann = LIVEDATA.announcements || [];
  return page({
    eyebrow: "Engage", title: "Announcements",
    desc: "Broadcast messages students see in the app.",
    body: ann.length ? rowsHtml(["Title", "Body", "Audience", "Date", ""],
      ann.map((a) =>
        cell('<strong style="font-size:12px">' + esc(a.title || "") + '</strong>') +
        cell('<span class="fa" style="font-size:11px">' + esc((a.body || "").slice(0, 60)) + '</span>') +
        cell('<span class="chip gy">' + esc(a.audience || "All") + '</span>') +
        cell(fd(a.createdAt), "tn fa") +
        cell('<button class="b bg2 xs" onclick="toast(\'Pinned\')">' + ic("pin", 12) + '</button>', "right")
      ).join("")
    ) : '<div class="empty"><b>No announcements yet</b>Create one to reach a group or the whole cohort</div>',
    actions: [{ label: "New announcement", fn: "openAnnouncementModal()", icon: "plus", primary: true }],
  });
}

function openAnnouncementModal() {
  openModal(
    '<p class="eyebrow">New announcement</p><h2 style="margin:6px 0 10px;font-size:17px">Broadcast to students</h2>' +
    '<div class="f"><label>Title</label><input id="na-title" placeholder="Announcement title"/></div>' +
    '<div class="f"><label>Body</label><textarea id="na-body" rows="3" placeholder="Message body…" style="width:100%;border:1px solid #E5E7EB;border-radius:8px;padding:9px;font:inherit;font-size:12.5px;resize:none"></textarea></div>' +
    '<div class="f"><label>Audience</label><select id="na-audience"><option>All batches</option><option>Group 1</option><option>Group 2</option></select></div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Cancel</button><button class="b bp sm" onclick="sendAnnouncement()">Publish</button></div>'
  );
}

async function sendAnnouncement() {
  const title = document.getElementById("na-title").value.trim();
  const body = document.getElementById("na-body").value.trim();
  const audience = document.getElementById("na-audience").value;
  if (!title || !body) { toast("Title and body required"); return; }
  try {
    await api("/whatsapp/announce", { method: "POST", body: JSON.stringify({ title, body, audience }) });
    toast("Announcement published");
    closeModal();
    LIVEDATA.announcements = LIVEDATA.announcements || [];
    LIVEDATA.announcements.unshift({ title, body, audience, createdAt: new Date().toISOString() });
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== BROADCASTS ===================== */
function sBroadcasts() {
  return page({
    eyebrow: "Engage", title: "Broadcasts",
    desc: "WhatsApp + app posts. Nothing sends without a preview.",
    body: '<div class="empty"><b>No broadcasts sent</b>Delivery log will appear here</div>',
    actions: [{ label: "New broadcast", fn: "openBroadcastModal()", icon: "chat", primary: true }],
  });
}

function openBroadcastModal() {
  openModal(
    '<p class="eyebrow">New broadcast</p><h2 style="margin:6px 0 10px;font-size:17px">WhatsApp broadcast</h2>' +
    '<div class="f"><label>Message</label><textarea id="nb-msg" rows="4" placeholder="Broadcast message…" style="width:100%;border:1px solid #E5E7EB;border-radius:8px;padding:9px;font:inherit;font-size:12.5px;resize:none"></textarea></div>' +
    '<div class="f"><label>Audience</label><select id="nb-audience"><option>All students</option><option>Group 1</option><option>Group 2</option></select></div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Cancel</button><button class="b bp sm" onclick="sendBroadcast()">Send</button></div>'
  );
}

async function sendBroadcast() {
  const message = document.getElementById("nb-msg").value.trim();
  const audience = document.getElementById("nb-audience").value;
  if (!message) { toast("Message required"); return; }
  try {
    await api("/whatsapp/broadcast", { method: "POST", body: JSON.stringify({ message, audience }) });
    toast("Broadcast sent");
    closeModal();
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== REPORTS ===================== */
function sReports() {
  const cur = S.tab.reports || "batch";
  return page({
    eyebrow: "Export", title: "Reports",
    desc: "Batch and student level reports.",
    tabs: [["batch", "Batch Report"], ["student", "Student Report"]],
    tab: cur, key: "reports",
    body: cur === "batch" ? batchReportBody() : studentReportBody(),
  });
}

function batchReportBody() {
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const tests = LIVEDATA.tests || [];
  const msgs = LIVEDATA.messages || [];

  // Subject averages from tests
  const subjMap = {};
  tests.forEach((t) => { if (t.subject) subjMap[t.subject] = subjMap[t.subject] || []; subjMap[t.subject].push(t.score); });
  const subjData = Object.keys(subjMap).map((s) => ({ label: s, value: Math.round(subjMap[s].reduce((a, b) => a + (b || 0), 0) / subjMap[s].length) }));

  // Batch distribution
  const batchMap = {};
  stu.forEach((s) => { batchMap[s.batch] = (batchMap[s.batch] || 0) + 1; });
  const batchData = Object.keys(batchMap).map((b) => ({ label: b, value: batchMap[b] }));

  return '<div class="row" style="gap:8px;margin-bottom:14px">' +
    '<div class="card" style="padding:11px 14px;flex:1"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Total students</div><div style="font-size:20px;font-weight:650">' + stu.length + '</div></div>' +
    '<div class="card" style="padding:11px 14px;flex:1"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Test submissions</div><div style="font-size:20px;font-weight:650">' + tests.length + '</div></div>' +
    '<div class="card" style="padding:11px 14px;flex:1"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Messages</div><div style="font-size:20px;font-weight:650">' + msgs.length + '</div></div>' +
    '<div class="card" style="padding:11px 14px;flex:1"><div class="fa" style="font-size:10.5px;text-transform:uppercase">Avg score</div><div style="font-size:20px;font-weight:650">' + (tests.length ? Math.round(tests.filter((t) => t.score != null).reduce((a, t) => a + (t.score || 0), 0) / tests.filter((t) => t.score != null).length) : 0) + '%</div></div>' +
  '</div>' +
  '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
    '<div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Students by batch</h3>' + C.barChart(batchData, { height: 160 }) + '</div>' +
    '<div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Subject averages</h3>' + C.barChart(subjData, { height: 160, colors: ["#7C3AED", "#DB2777", "#0284C7", "#D97706", "#16A34A"] }) + '</div>' +
  '</div>' +
  '<div style="margin-top:14px"><div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Detailed student report</h3>' +
  rowsHtml(["Student", "Batch", "Group", "Streak", "Hours", "Tests", "Status"],
    stu.map((s) =>
      cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) +
      cell(s.streak || 0, "tn") + cell((s.totalHours || 0) + "h", "tn") + cell((s.tests || []).length, "tn") +
      cell('<span class="tag ' + band(s)[1] + '">' + band(s)[0] + '</span>')
    ).join(""), "No students"
  ) + '</div></div>' +
  '<div class="row" style="margin-top:12px;justify-content:flex-end"><button class="b bp sm" onclick="exportCsv()">' + ic("download", 14) + ' Export CSV</button></div>';
}

function studentReportBody() {
  return '<div class="empty"><b>Student Report</b><br/>Select a student from the Students page to view their detailed report with mastery journey, chapter table, test stats, and recommendations.</div>';
}

/* ===================== ACCESS CONTROL ===================== */
async function setStudentAccess(studentId, action) {
  try {
    const res = await api("/student-dashboard/write", {
      method: "POST",
      body: JSON.stringify({
        action: "students.setAccess",
        studentId: studentId,
        action_type: action
      })
    });
    if (res.ok) {
      toast(action === "block" ? "Access blocked for " + studentId :
            action === "restore" ? "Access restored for " + studentId :
            action === "archive" ? "Removed from program: " + studentId :
            "Student restored to program: " + studentId);
      await loadData();
      draw();
    } else {
      toast("Error: " + (res.message || "Failed"));
    }
  } catch (e) {
    toast("Error: " + e.message);
  }
}

function sAccess() {
  const allStu = LIVEDATA.students || [];
  const stu = allStu.filter((s) => !s.archived);
  const blocked = stu.filter((s) => s.access === false);
  const active = stu.filter((s) => s.access !== false);
  const selId = S.selAccess || (blocked[0] && blocked[0].id) || null;
  const selStu = stu.find((s) => s.id === selId);

  const sidebarHtml = blocked.length ?
    '<div class="access-side">' +
      '<div class="sh">' + ic("shield", 12) + ' Access — No app access (' + blocked.length + ')</div>' +
      '<div class="ct">' +
        blocked.map((s) =>
          '<button class="access-item ' + (s.id === selId ? "sel" : "") + '" onclick="S.selAccess=\'' + s.id + '\';draw()">' +
            '<span class="av gy">' + esc((s.name || s.id || "?")[0]) + '</span>' +
            '<span style="flex:1;min-width:0"><span class="nm">' + esc(s.name || s.id) + '</span><br/><span class="mt">' + esc(s.batch || "—") + '</span></span>' +
            '<span class="bdg">' + (s.streak || 0) + 'd</span>' +
          '</button>'
        ).join("") +
      '</div>' +
    '</div>' :
    '<div class="access-side"><div class="sh">Access</div><div class="empty"><b>No blocked students</b>Everyone has app access.</div></div>';

  const detailHtml = selStu ?
    '<div class="card" style="padding:16px">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">' +
        '<span class="av" style="width:40px;height:40px;font-size:14px">' + esc((selStu.name || selStu.id || "?")[0]) + '</span>' +
        '<div><div style="font-size:15px;font-weight:600">' + esc(selStu.name || selStu.id) + '</div>' +
        '<div class="fa" style="font-size:12px">' + esc(selStu.batch || "—") + ' · ' + esc(selStu.group || "—") + '</div></div>' +
      '</div>' +
      '<div class="kv">' +
        '<span>Student ID</span><b>' + esc(selStu.id) + '</b>' +
        '<span>Status</span><b>' + (selStu.access === false ? '<span class="tag r">No access</span>' : '<span class="tag g">Active</span>') + '</b>' +
        '<span>Streak</span><b>' + (selStu.streak || 0) + ' days</b>' +
        '<span>Total Hours</span><b>' + (selStu.totalHours || selStu.lb || 0) + '</b>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">' +
        (selStu.access === false ?
          '<button class="b bp sm" onclick="setStudentAccess(\'' + selStu.id + '\',\'restore\')">' + ic("restore", 14) + ' Restore Access</button>'
          :
          '<button class="b bg2 sm" onclick="setStudentAccess(\'' + selStu.id + '\',\'block\')">' + ic("shield", 14) + ' Block Access</button>' +
          '<button class="b danger sm" onclick="setStudentAccess(\'' + selStu.id + '\',\'archive\')">' + ic("trash", 14) + ' Remove from Program</button>'
        ) +
      '</div>' +
    '</div>' :
    '<div class="empty"><b>Select a student</b>Click a student on the left to view details and manage their access.</div>';

  const activeTable = active.length ?
    rowsHtml(["Student", "Batch", "Group", "Streak", "Status", "Actions"],
      active.map((s) =>
        cell(personCell(s)) + cell('<span class="chip gy">' + esc(s.batch || "—") + '</span>') + cell(gchip(s.group)) +
        cell(s.streak || 0, "tn") +
        cell('<span class="tag ' + band(s)[1] + '">' + band(s)[0] + '</span>') +
        cell(
          '<div style="display:flex;gap:4px;justify-content:flex-end">' +
            '<button class="b bg2 xs" onclick="S.selAccess=\'' + s.id + '\';draw()">' + ic("eye", 11) + '</button>' +
            '<button class="b bg2 xs" onclick="setStudentAccess(\'' + s.id + '\',\'block\')">' + ic("shield", 11) + ' Block</button>' +
            '<button class="b danger xs" onclick="setStudentAccess(\'' + s.id + '\',\'archive\')">' + ic("trash", 11) + '</button>' +
          '</div>', "right"
        )
      ).join(""), "No active students"
    ) : '<div class="empty"><b>No active students</b></div>';

  return page({
    eyebrow: "Admin", title: "Access Control",
    desc: "Block app access, remove students from the program, or restore access.",
    stats: [
      ["No access", blocked.length, "#D97706"],
      ["Active", active.length, "#16A34A"],
      ["Archived", allStu.filter((s) => s.archived).length, "#9CA3AF"],
      ["Total", allStu.length, "#111827"],
    ],
    body: '<div class="access-split">' + sidebarHtml + '<div>' + detailHtml +
      '<div class="card" style="margin-top:14px">' +
        '<div style="padding:12px 15px;border-bottom:1px solid var(--bd2);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--fa)">' + ic("check", 12) + ' Active Students (' + active.length + ')</div>' +
        activeTable +
      '</div>' +
    '</div></div>',
  });
}

/* ===================== MCQ REVIEW ===================== */
function sAicontent() {
  return page({
    eyebrow: "Content", title: "MCQ Review",
    desc: "Approve chapter MCQs before students see them.",
    body: '<div class="empty"><b>Review queue</b><br/>Approve or reject AI-generated MCQs before they go live to students.<br/><br/><button class="b bp sm" onclick="toast(\'Loading review queue…\')">' + ic("book", 14) + ' Load review queue</button></div>',
  });
}

/* ===================== NOTES INBOX ===================== */
function sNotesinbox() {
  return page({
    eyebrow: "Content", title: "Notes Inbox",
    desc: "AI-prepared notes — publish or skip.",
    body: '<div class="empty"><b>Inbox is empty</b>New AI-prepared notes will land here for review.</div>',
  });
}

/* ===================== PASSWORD RESET ===================== */
function sPasswords() {
  return page({
    eyebrow: "Admin", title: "Password Reset",
    desc: "Queue, set a new password, and history.",
    body: '<div class="empty"><b>No reset requests</b>Student password reset requests appear here.</div>',
  });
}

/* ===================== SHEET SOURCES ===================== */
function sSheets() {
  return page({
    eyebrow: "Admin", title: "Sheet Sources",
    desc: "Mongo is the source of truth. Manual sync only.",
    body: rowsHtml(["Source", "Rows", "Last sync", "Status"],
      [
        '<tr>' + cell('<strong>Students Sheet</strong>') + cell("374", "tn") + cell("20 Oct 2026", "tn fa") + cell('<span class="tag g">ok</span>') + '</tr>',
        '<tr>' + cell('<strong>Form responses</strong>') + cell("336", "tn") + cell("31 Oct 2026", "tn fa") + cell('<span class="tag g">ok</span>') + '</tr>',
        '<tr>' + cell('<strong>Mongo study logs</strong>') + cell("2,695", "tn") + cell("31 Oct 2026", "tn fa") + cell('<span class="tag g">ok</span>') + '</tr>',
      ]
    ),
  });
}

/* ===================== SETTINGS ===================== */
function sSettings() {
  const cur = S.tab.settings || "roles";
  let body;
  if (cur === "roles") {
    body = rowsHtml(["Mentor", "Role", "Access"],
      '<tr>' + cell('<strong>Ujjwal Pathak</strong>') + cell('<span class="chip dy">Owner</span>') + cell('<span class="fa">Full access</span>') + '</tr>' +
      '<tr>' + cell('<strong>Coordinator</strong>') + cell('<span class="chip gy">Coordinator</span>') + cell('<span class="fa">Operations</span>') + '</tr>' +
      '<tr>' + cell('<strong>Mentor</strong>') + cell('<span class="chip gy">Mentor</span>') + cell('<span class="fa">Scoped view</span>') + '</tr>'
    );
  } else if (cur === "batches") {
    const m = {};
    (LIVEDATA.students || []).filter((s) => !s.archived).forEach((s) => { m[s.batch] = (m[s.batch] || 0) + 1; });
    body = rowsHtml(["Batch", "Students", "Status"],
      Object.keys(m).map((b) => '<tr>' + cell('<strong>' + esc(b) + '</strong>') + cell(m[b], "tn") + cell('<span class="tag g">Active</span>') + '</tr>').join("")
    );
  } else {
    body = rowsHtml(["Check", "Result"],
      '<tr>' + cell("Roster students") + cell((LIVEDATA.students || []).filter((s) => !s.archived).length, "tn") + '</tr>' +
      '<tr>' + cell("Archived students") + cell((LIVEDATA.students || []).filter((s) => s.archived).length, "tn") + '</tr>' +
      '<tr>' + cell("Test submissions") + cell((LIVEDATA.tests || []).length, "tn") + '</tr>' +
      '<tr>' + cell("Message threads") + cell((LIVEDATA.messages || []).length, "tn") + '</tr>'
    );
  }
  return page({
    eyebrow: "Admin", title: "Settings",
    desc: "Mentors, cohorts and data rules.",
    tabs: [["roles", "Mentors & roles"], ["batches", "Cohorts"], ["quality", "Data quality"]],
    tab: cur, key: "settings",
    body: body,
  });
}

/* ===================== ANALYTICS ===================== */
function sAnalytics() {
  const ov = LIVEDATA.analytics || {};
  const stu = (LIVEDATA.students || []).filter((s) => !s.archived);
  const bandMap = {};
  stu.forEach((s) => { const b = band(s)[0]; bandMap[b] = (bandMap[b] || 0) + 1; });
  const perfData = Object.keys(bandMap).map((k) => ({ label: k, value: bandMap[k] }));

  return page({
    eyebrow: "Consented students only", title: "Analytics",
    desc: "Chapter mastery and cohort overview from the analytics API.",
    stats: [["Students", stu.length], ["Tests", (LIVEDATA.tests || []).length], ["Messages", (LIVEDATA.messages || []).length]],
    body: '<div class="card" style="padding:14px"><h3 style="font-size:13px;margin:0 0 8px">Mastery distribution</h3>' + C.doughnutChart(perfData, { size: 160 }) + '</div>' +
    '<div class="card" style="padding:14px;margin-top:12px"><h3 style="font-size:13px;margin:0 0 8px">Cohort overview</h3>' +
    rowsHtml(["Metric", "Value"],
      [
        '<tr>' + cell("Total students") + cell(stu.length, "tn") + '</tr>',
        '<tr>' + cell("Active students") + cell(stu.filter((s) => s.streak > 0).length, "tn") + '</tr>',
        '<tr>' + cell("At-risk students") + cell(stu.filter((s) => band(s)[0] === "Weak" || band(s)[0] === "Inactive").length, "tn") + '</tr>',
        '<tr>' + cell("Avg streak") + cell(Math.round(stu.reduce((a, s) => a + (s.streak || 0), 0) / Math.max(1, stu.length)), "tn") + '</tr>',
      ]
    ) + '</div>',
  });
}

/* ===================== FOLLOW-UPS ===================== */
function sFollowup() {
  return page({
    eyebrow: "Consented students only", title: "Follow-ups",
    desc: "Open follow-ups from the analytics API.",
    body: '<div class="empty"><b>No open follow-ups</b>Create a follow-up to track a student who needs extra attention.</div>',
    actions: [{ label: "New follow-up", fn: "openFollowupModal()", icon: "plus", primary: true }],
  });
}

function openFollowupModal() {
  openModal(
    '<p class="eyebrow">New follow-up</p><h2 style="margin:6px 0 10px;font-size:17px">Track a student</h2>' +
    '<div class="f"><label>Student ID</label><input id="fu-student" placeholder="e.g. UMP0011"/></div>' +
    '<div class="f"><label>Note</label><textarea id="fu-note" rows="3" placeholder="What needs follow-up?" style="width:100%;border:1px solid #E5E7EB;border-radius:8px;padding:9px;font:inherit;font-size:12.5px;resize:none"></textarea></div>' +
    '<div class="f"><label>Priority</label><select id="fu-priority"><option>Normal</option><option>High</option><option>Low</option></select></div>' +
    '<div class="row" style="margin-top:13px;justify-content:flex-end"><button class="b bg2 sm" onclick="closeModal()">Cancel</button><button class="b bp sm" onclick="saveFollowup()">Save</button></div>'
  );
}

async function saveFollowup() {
  const studentId = document.getElementById("fu-student").value.trim().toUpperCase();
  const note = document.getElementById("fu-note").value.trim();
  const priority = document.getElementById("fu-priority").value;
  if (!studentId) { toast("Student ID required"); return; }
  try {
    await api("/analytics/followups", { method: "POST", body: JSON.stringify({ studentId, note, priority }) });
    toast("Follow-up created for " + studentId);
    closeModal();
    draw();
  } catch (err) { toast(err.message); }
}

/* ===================== REGISTER SCREENS ===================== */
window.UMP_SCREENS = {
  dash: sDash,
  batches: sBatches,
  students: sStudents,
  tracker: sTracker,
  targets: sTargets,
  plans: sPlans,
  coverage: sCoverage,
  startdates: sStartdates,
  leader: sLeader,
  messages: sMessages,
  tests: sTests,
  mcqscores: sMcqScores,
  notes: sNotes,
  announcements: sAnnouncements,
  broadcasts: sBroadcasts,
  reports: sReports,
  access: sAccess,
  aicontent: sAicontent,
  notesinbox: sNotesinbox,
  passwords: sPasswords,
  sheets: sSheets,
  settings: sSettings,
  analytics: sAnalytics,
  followup: sFollowup,
  openDrawer: openStudent,
};
