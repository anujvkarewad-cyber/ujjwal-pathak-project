/**
 * Mentor Dashboard — Core application logic.
 * Single-file vanilla JS, no build step, no external dependencies.
 * Uses same-origin /api/mentor path (gateway strips prefix → backend).
 */
"use strict";

/* ===================== CONSTANTS ===================== */
const API_BASE = (window.UMP_MENTOR_API_URL || "/api").replace(/\/+$/, "");

const TRACKS = ["Group 1", "Group 2", "Both"];

/* ===================== STATE ===================== */
const S = {
  role: "Owner",
  screen: null,
  authed: false,
  filter: "all",
  seg: "all",
  sort: "att",
  page: 1,
  per: 20,
  sel: new Set(),
  q: "",
  tab: {},
  dtab: {},
  sort2: {},
  filters: { batch: "All", group: "All", seg: "All" },
  thread: null,
  drawer: null,
};

/* ===================== ICONS ===================== */
const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  check: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  note: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  chart: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
  inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  chat: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  key: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  arrow: '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  dl: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  chevron: '<polyline points="9 18 15 12 9 6"/>',
  inbox2: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
  warn: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  play: '<polygon points="5 3 19 12 5 21 5 3"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
  filter: '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
  home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  medal: '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
  crown: '<path d="M2 7l5 5 5-7 5 7 5-5-2 12H4z"/>',
  award: '<circle cx="12" cy="8" r="6"/><path d="M15.5 13.5L17 22l-5-3-5 3 1.5-8.5"/>',
  trend: '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
  fire: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  book2: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  star2: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" fill="currentColor" stroke="none"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  pin: '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  restore: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
};

function ic(name, size) {
  const path = ICONS[name] || ICONS.note;
  return '<svg width="' + (size || 16) + '" height="' + (size || 16) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
}

/* ===================== HELPERS ===================== */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fd(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });
  } catch { return iso; }
}

function fdFull(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  } catch { return iso; }
}

function ini(name) {
  const parts = String(name || "").trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function band(s) {
  const hrs = s.totalHours || 0;
  if (hrs < 5) return ["Not started", "n"];
  if (s.streak >= 5 && hrs >= 20) return ["Mastered", "g"];
  if (s.streak >= 3 || hrs >= 10) return ["Strong", "g"];
  if (s.streak >= 1 || hrs >= 5) return ["Medium", "a"];
  if (s.lb && s.lb.status === "Inactive") return ["Inactive", "r"];
  return ["Weak", "r"];
}

function gchip(g) {
  const map = { "Group 1": "g1", "Group 2": "g2", "Both": "bo" };
  return '<span class="chip ' + (map[g] || "gy") + '">' + esc(g || "—") + '</span>';
}

function cell(html, cls) {
  return '<td class="' + (cls || "") + '">' + html + '</td>';
}

function rowsHtml(cols, rows, empty) {
  if (!rows || !rows.length) return '<div class="empty">' + (empty || "No results") + '</div>';
  return '<table><thead><tr>' + cols.map((c) => '<th>' + c + '</th>').join("") + '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function personCell(s) {
  return '<span style="display:inline-flex;align-items:center;gap:7px"><span class="av" style="width:24px;height:24px;font-size:9.5px">' + ini(s.name) + '</span><strong style="font-size:12.5px">' + esc(s.name) + '</strong></span>';
}

function reasonChips(s) {
  const o = [];
  if (s.today && s.today.status === "missed") o.push('<span class="tag r">No submission</span>');
  if (s.hist && s.hist.missedDays > 0) o.push('<span class="tag a">' + s.hist.missedDays + 'd missed</span>');
  if (s.access === false) o.push('<span class="tag r">No app access</span>');
  if (s.tests && s.tests.length && Math.min.apply(null, s.tests.map((t) => t.score || 100)) < 50) o.push('<span class="tag a">Low test</span>');
  return o.join(" ") || '<span class="fa">—</span>';
}

/* ===================== API ===================== */
async function api(path, options) {
  const token = localStorage.getItem("ump_mentor_token");
  const headers = Object.assign({}, options && options.headers || {}, {});
  if (token) headers["Authorization"] = "Bearer " + token;
  if (options && options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers: headers }));
  if (res.status === 401) { logout(); throw new Error("Session expired. Sign in again."); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || err.error || "Request failed (" + res.status + ")");
  }
  return res.json();
}

/* ===================== AUTH ===================== */
async function doLogin() {
  const email = document.getElementById("lgemail").value.trim();
  const password = document.getElementById("lgpass").value;
  if (!email || !password) return;
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    if (!data.token) throw new Error("No token in response");
    localStorage.setItem("ump_mentor_token", data.token);
    localStorage.setItem("ump_mentor_email", data.email || email);
    S.authed = true;
    S.role = data.role || "Mentor";
    toast("Welcome, " + (data.email || email));
    loadData().then(() => { S.screen = "dash"; draw(); });
  } catch (err) {
    const el = document.getElementById("lgnote");
    if (el) el.textContent = err.message || "Could not sign in";
  }
}

function enterDemo() {
  localStorage.setItem("ump_mentor_token", "demo-token");
  localStorage.setItem("ump_mentor_email", "demo@mentor.local");
  S.authed = true;
  S.role = "Owner";
  toast("Demo mode — using live API");
  loadData().then(() => { S.screen = "dash"; draw(); });
}

function logout() {
  localStorage.removeItem("ump_mentor_token");
  localStorage.removeItem("ump_mentor_email");
  S.authed = false;
  S.screen = null;
  S.thread = null;
  S.drawer = null;
  draw();
}

/* ===================== DATA LOADING ===================== */
let LIVEDATA = null;
let DATA_LOADED = false;

async function loadData() {
  if (DATA_LOADED) return LIVEDATA;
  LIVEDATA = { students: [], tests: [], messages: [], targets: [], analytics: {}, leaderboard: [], tracker: {}, notes: [], announcements: [], roster: [] };
  const tasks = [
    // Tracker-day returns the full roster (344 students) with daily tracker entries
    api("/student-dashboard/tracker-day").then((d) => {
      LIVEDATA.tracker = d;
      LIVEDATA.students = (d.list || []).map((s) => ({
        id: s.id, studentId: s.id, name: s.name, studentName: s.name,
        batch: s.batch, group: s.group, avatar: s.avatar,
        notExpected: s.notExpected, effectiveStart: s.effectiveStart,
        today: s.entry, entry: s.entry,
      }));
      LIVEDATA.roster = LIVEDATA.students;
    }).catch(() => {}),
    // Leaderboard returns segments with ranked entries
    api("/student-dashboard/leaderboard").then((d) => {
      LIVEDATA.leaderboard = [];
      (d.segments || []).forEach((seg) => {
        (seg.entries || []).forEach((e) => {
          LIVEDATA.leaderboard.push(Object.assign({}, e, { segment: seg.key, segmentLabel: seg.label }));
        });
      });
    }).catch(() => {}),
    api("/test-history").then((d) => { LIVEDATA.tests = d.entries || d || []; }).catch(() => {}),
    api("/messages/inbox").then((d) => { LIVEDATA.messages = d.threads || d || []; }).catch(() => {}),
    api("/targets").then((d) => { LIVEDATA.targets = d.targets || d || []; }).catch(() => {}),
    api("/analytics/overview").then((d) => { LIVEDATA.analytics = d; }).catch(() => {}),
  ];
  await Promise.all(tasks);
  // Merge leaderboard data into student objects by studentId
  const lbMap = {};
  (LIVEDATA.leaderboard || []).forEach((e) => { lbMap[e.studentId] = e; });
  (LIVEDATA.students || []).forEach((s) => {
    if (lbMap[s.studentId]) {
      s.lb = lbMap[s.studentId];
      s.streak = s.lb.streak || 0;
      s.totalHours = s.lb.totalHours || 0;
      s.rank = s.lb.rank;
      s.score = s.lb.score;
      s.attendance = s.lb.attendance;
    }
  });
  DATA_LOADED = true;
  return LIVEDATA;
}

/* ===================== ROUTER ===================== */
function go(screen) {
  S.screen = screen;
  S.page = 1;
  S.q = "";
  draw();
}

function draw() {
  const app = document.getElementById("app");
  if (!S.authed || !S.screen) {
    app.innerHTML = loginScreen();
    wireLogin();
    return;
  }
  const screens = window.UMP_SCREENS || {};
  const fn = screens[S.screen];
  if (!fn) { app.innerHTML = "<div style='padding:40px'>Screen not found: " + S.screen + "</div>"; return; }
  try {
    const body = fn();
    app.innerHTML = shell(body);
    // Show drawer if a student is selected
    const drw = document.getElementById("drw");
    if (drw) {
      if (S.drawer && window.UMP_SCREENS && window.UMP_SCREENS.openDrawer) {
        window.UMP_SCREENS.openDrawer(S.drawer);
        drw.classList.add("on");
      } else {
        drw.classList.remove("on");
      }
    }
  } catch (err) {
    console.error("Screen error:", err);
    app.innerHTML = shell('<div class="empty"><b>Error</b>' + esc(err.message) + '</div>');
  }
}

/* ===================== SHELL ===================== */
const NAV = [
  { label: "Main", items: [
    ["Dashboard", "dash", "grid"],
    ["Batches & groups", "batches", "layers"],
    ["Students", "students", "users"],
    ["Daily Tracker", "tracker", "check"],
    ["Daily Targets", "targets", "target"],
    ["Target Plans", "plans", "note"],
    ["Coverage", "coverage", "shield"],
    ["Start Dates", "startdates", "clock"],
    ["Leaderboard", "leader", "chart"],
    ["Messages", "messages", "inbox"],
    ["Tests", "tests", "note"],
    ["MCQ Scores", "mcqscores", "chart"],
    ["Notes", "notes", "note"],
    ["Announcements", "announcements", "bell"],
    ["Broadcasts", "broadcasts", "chat"],
    ["Reports", "reports", "file"],
    ["Access Control", "access", "shield"],
  ]},
  { label: "Content", items: [
    ["MCQ Review", "aicontent", "book"],
    ["Notes Inbox", "notesinbox", "inbox"],
    ["Password Reset", "passwords", "key"],
    ["Sheet Sources", "sheets", "link"],
    ["Settings", "settings", "gear"],
  ]},
  { label: "Analytics", items: [
    ["Overview", "analytics", "chart"],
    ["Follow-ups", "followup", "bell"],
  ]},
];

const TITLES = {
  dash: "Dashboard", batches: "Batches & groups", students: "Students",
  tracker: "Daily Tracker", targets: "Daily Targets", plans: "Target Plans",
  coverage: "Coverage", startdates: "Start Dates", leader: "Leaderboard",
  messages: "Messages", tests: "Tests", mcqscores: "MCQ Scores",
  notes: "Notes", announcements: "Announcements", broadcasts: "Broadcasts",
  reports: "Reports", analytics: "Analytics", followup: "Follow-ups",
  aicontent: "MCQ Review", notesinbox: "Notes Inbox", passwords: "Password Reset",
  sheets: "Sheet Sources", settings: "Settings", access: "Access Control",
};

function shell(body) {
  const email = localStorage.getItem("ump_mentor_email") || "mentor";
  const navHtml = NAV.map((g) =>
    '<p class="nl">' + g.label + '</p>' +
    g.items.map((item) => {
      const [label, key, icon] = item;
      return '<button class="ni ' + (S.screen === key ? "on" : "") + '" onclick="go(\'' + key + '\')">' + ic(icon) + '<span>' + label + '</span></button>';
    }).join("")
  ).join("");

  return '<div class="shell">' +
    '<aside class="sb">' +
      '<div class="sb-top"><span class="bm">UP</span><span style="font-size:13px;font-weight:600">Ujjwal Pathak</span></div>' +
      '<nav class="nav">' + navHtml + '</nav>' +
      '<div class="sb-bot">' +
        '<button class="pmini" onclick="logout()"><span class="av">UP</span><span style="text-align:left;flex:1"><strong>' + esc(email) + '</strong><small>' + S.role + '</small></span>' + ic("logout", 14) + '</button>' +
      '</div>' +
    '</aside>' +
    '<div class="main">' +
      '<header class="top">' +
        '<div class="cr"><span>Mentor desk</span>' + ic("arrow", 13) + '<strong>' + (TITLES[S.screen] || "Dashboard") + '</strong></div>' +
        '<div class="srch"><span style="position:absolute;left:8px;top:8px;color:#9CA3AF">' + ic("search", 14) + '</span><input placeholder="Search student, batch…" value="' + esc(S.q) + '" oninput="S.q=this.value;draw()"></div>' +
        '<span class="pl gn"><span class="dot" style="background:#16A34A"></span>Live data</span>' +
        '<button class="ib" onclick="go(\'messages\')">' + ic("inbox", 15) + '</button>' +
        '<span class="av" title="' + S.role + '">UP</span>' +
      '</header>' +
      '<main class="ct">' + body + '</main>' +
    '</div>' +
    '<div class="drw" id="drw"><div class="drw-h" id="dh"></div><div class="drw-t" id="dtabs"></div><div class="drw-b" id="db"></div></div>' +
    '<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><div class="mbox" id="mbox"></div></div>' +
    '<div class="toast" id="toast"></div>' +
  '</div>';
}

/* ===================== PAGE PATTERN ===================== */
function page(o) {
  const tabs = o.tabs && o.tabs.length
    ? '<div class="tabs">' + o.tabs.map((t) => '<button class="tab ' + (o.tab === t[0] ? "on" : "") + '" onclick="S.tab.' + o.key + '=\'' + t[0] + '\';S.page=1;draw()">' + t[1] + (t[2] != null ? ' <span class="fa">' + t[2] + '</span>' : '') + '</button>').join("") + '</div>'
    : '';
  const actions = (o.actions || []).map((a) => '<button class="b ' + (a.primary ? "bp" : "bg2") + ' sm" onclick="' + a.fn + '">' + (a.icon ? ic(a.icon, 14) : '') + a.label + '</button>').join("");
  const stats = o.stats && o.stats.length
    ? '<div class="row" style="gap:8px;margin-bottom:12px">' + o.stats.map((st) => '<div class="card" style="padding:11px 14px;flex:1;min-width:120px"><div class="fa" style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em">' + esc(st[0]) + '</div><div class="tn" style="font-size:20px;font-weight:650;' + (st[2] ? 'color:' + st[2] : '') + '">' + st[1] + '</div></div>').join("") + '</div>'
    : '';
  return '<div class="ph"><div><p class="eyebrow">' + esc(o.eyebrow || "") + '</p><h1>' + esc(o.title) + '</h1>' + (o.desc ? '<p class="d">' + o.desc + '</p>' : '') + '</div><div class="row" style="flex-wrap:wrap">' + actions + '</div></div>' + stats + '<section class="card">' + tabs + o.body + '</section>' + (o.note ? '<div class="nl2">' + o.note + '</div>' : '');
}

function listScreen(o) {
  const rows = typeof o.rows === "function" ? o.rows() : o.rows || [];
  let filtered = rows;
  if (o.searchable && S.q) {
    const q = S.q.toLowerCase();
    filtered = rows.filter((r) => (o.searchText(r) || "").toLowerCase().includes(q));
  }
  if (o.tabs) {
    const cur = S.tab[o.key] || o.tabs[0][0];
    const tabRows = o.rowsForTab ? o.rowsForTab(cur, filtered) : filtered.filter((r) => {
      // default: no filtering by tab unless rowsForTab is provided
      return true;
    });
    filtered = tabRows;
  }
  const slice = filtered.slice((S.page - 1) * S.per, S.page * S.per);
  const body = (typeof o.render === "function") ? o.render(slice) : rowsHtml(o.cols, slice.join(""));
  const totalPages = Math.max(1, Math.ceil(filtered.length / S.per));
  const pgr = totalPages > 1 ? '<div class="row" style="justify-content:center;padding:10px;gap:6px">' + (S.page > 1 ? '<button class="b bg2 xs" onclick="S.page--;draw()">Prev</button>' : '') + '<span class="fa" style="font-size:12px">' + S.page + ' / ' + totalPages + '</span>' + (S.page < totalPages ? '<button class="b bg2 xs" onclick="S.page++;draw()">Next</button>' : '') + '</div>' : '';
  return page({ eyebrow: o.eyebrow, title: o.title, desc: o.desc, key: o.key, tab: S.tab[o.key], tabs: o.tabs, body: body + pgr, empty: o.empty });
}

/* ===================== TOAST ===================== */
let toastTimer = null;
function toast(msg) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("on");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("on"), 2800);
}

/* ===================== MODAL ===================== */
function openModal(html) {
  document.getElementById("mbox").innerHTML = html;
  document.getElementById("modal").classList.add("on");
}
function closeModal() {
  document.getElementById("modal").classList.remove("on");
}

/* ===================== LOGIN SCREEN ===================== */
function loginScreen() {
  return '<div class="login">' +
    '<div class="lg-art">' +
      '<div><p class="eyebrow" style="color:rgba(255,255,255,.5)">Ujjwal Pathak · Mentorship</p><h1>Mentor <em>Desk</em></h1><p>Same login as the live dashboard. Sign in to manage students, track progress, and review submissions.</p></div>' +
      '<div class="lg-foot"><span>' + ic("shield", 12) + ' Private · chapter summaries only</span><span>' + ic("chart", 12) + ' Live API data</span></div>' +
    '</div>' +
    '<div class="lg-panel"><div class="lgcard">' +
      '<p class="eyebrow" style="color:#9CA3AF">Mentor sign in</p>' +
      '<h2>Welcome back</h2>' +
      '<p class="fa" style="font-size:12.5px;margin:4px 0 16px">Sign in to continue to your dashboard.</p>' +
      '<div class="f"><label>Mentor ID (email)</label><input id="lgemail" type="email" value="mentor@ujjwalpathak.in" placeholder="mentor@example.com" autocomplete="username"/></div>' +
      '<div class="f"><label>Password</label><input id="lgpass" type="password" value="1234567" placeholder="••••••••" autocomplete="current-password"/></div>' +
      '<div id="lgnote" class="fa" style="font-size:11.5px;color:#DC2626;min-height:16px;margin-bottom:8px"></div>' +
      '<button class="b bp bw" onclick="doLogin()">Sign in</button>' +
      '<button class="b bg2 bw" style="margin-top:8px" onclick="enterDemo()">' + ic("play", 14) + ' Continue with demo data</button>' +
    '</div></div>' +
  '</div>';
}

function wireLogin() {
  const pass = document.getElementById("lgpass");
  if (pass) pass.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
  const email = document.getElementById("lgemail");
  if (email) email.addEventListener("keydown", (e) => { if (e.key === "Enter") document.getElementById("lgpass").focus(); });
}

/* ===================== INIT ===================== */
draw();
