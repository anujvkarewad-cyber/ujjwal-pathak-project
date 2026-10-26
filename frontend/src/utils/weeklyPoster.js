/**
 * The weekly WhatsApp poster: one card per batch x group board, per week.
 *
 * The mentor posts these into each group's WhatsApp after the week closes
 * (the week runs Sunday -> Saturday, so a finished week is ready on Sunday
 * evening), so the layout follows the creative he already uses: dark + gold,
 * three podiums, name and hours only — no score, no roll number, nothing a
 * student could read as surveillance.
 *
 * Pure SVG-as-string on purpose:
 *   * it is data, not a picture — a wrong name is a bug we can test;
 *   * the browser rasterises it to PNG for WhatsApp with no upload, no image
 *     service and no API key;
 *   * it previews inside the mentor dashboard, which cannot fetch fonts.
 *
 * Deliberately FLAT colours and fixed-width ribbons: the card is rasterised by
 * whatever engine the mentor's browser has, and a name must never spill past
 * its ribbon (the first draft did exactly that with "NITIN YADAV"), so every
 * variable string gets textLength + lengthAdjust and cannot overflow.
 */

export const W = 1080;
export const H = 1350;

/** The mentor's brand block. One place to change if "SUPER 75" is renamed. */
export const BRAND = {
  kicker: 'CA INTER',
  name: 'SUPER 75',
  tagline: 'DISCIPLINE  |  PRACTICE  |  PROGRESS',
  notesLeft: ['Same', 'Students', 'Different', 'Mindset'],
  notesRight: ['Consistent', 'Students', 'Always Win'],
  closer: 'Keep it Up!',
  // The owner's line for every group post (18-Oct): rank is earned by the
  // daily record, so a missing submission is framed as the student's own
  // responsibility - not as a threat from the mentor.
  duty: '📌 Yaad rakhiye: rank wahi banta hai jo roz tracker bhejta hai. Ek din submit nahi kiya = wo din aapke record me zero hai, aur rank neeche chala jaata hai — mehnat kam hone par nahi, record na hone par. Daily submission aapki zimmedari hai. Roz 1 minute ✅',
  footer: ['CONSISTENT EFFORT', 'BETTER RESULTS', 'STRONGER CONCEPTS', 'CLOSER TO YOUR GOAL'],
};

const GOLD = '#E4BB55';
const GOLD_LIGHT = '#F8E5B0';
const GOLD_DARK = '#8A6A1E';
const INK = '#0A0A0C';

const MEDALS = {
  1: { ring: GOLD, ribbon: GOLD, ribbonText: '#2A2005', plate: GOLD_LIGHT, label: '1' },
  2: { ring: '#C9CFD8', ribbon: '#D7DCE3', ribbonText: '#242A32', plate: '#EDF0F4', label: '2' },
  3: { ring: '#C98A5A', ribbon: '#C58A57', ribbonText: '#38200C', plate: '#E7BE97', label: '3' },
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** "11–17 Oct 2026" — same shape the dashboard shows, so card and screen agree. */
export function weekLabel(weekStart, weekEnd) {
  const from = new Date(weekStart);
  const to = new Date(weekEnd);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return '';
  const left = from.getMonth() === to.getMonth()
    ? String(from.getDate())
    : `${from.getDate()} ${MONTHS[from.getMonth()] || ''}`;
  return `${left}–${to.getDate()} ${MONTHS[to.getMonth()] || ''} ${to.getFullYear()}`;
}

/** "BATCH 1" + "GROUP 1" (or "BOTH GROUPS") from the board's own strings. */
export function boardLines(batch, group) {
  const nums = String(batch || '').match(/\d+/g);
  const line1 = nums ? `BATCH ${nums[nums.length - 1]}` : (String(batch || '').toUpperCase() || 'BATCH');
  const g = String(group || '').trim().toUpperCase();
  let line2 = 'BOTH GROUPS';
  if (g.includes('NO GROUP')) line2 = 'GROUP NOT SET';
  else if (g && !g.includes('BOTH')) line2 = `GROUP ${g.replace(/^GROUP\s*/, '')}`;
  return [line1, line2];
}

function hoursText(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(1) : '0.0';
}

/** Names are the one unbounded string on the card — clamp what we draw, not the box. */
function displayName(name) {
  const clean = String(name || '').trim().replace(/\s+/g, ' ').toUpperCase();
  if (!clean) return '—';
  if (clean.length <= 22) return clean;
  const cut = clean.slice(0, 21);
  const space = cut.lastIndexOf(' ');
  return `${(space >= 10 ? cut.slice(0, space) : cut).trim()}…`;
}

/** A ribbon that always fits: fixed plate, text squeezed to fit its width. */
function ribbon(cx, cy, width, medal, text, size = 27) {
  const m = MEDALS[medal];
  const half = width / 2;
  const tail = 20;
  return `
    <path d="M ${cx - half - tail} ${cy} l ${tail} -22 h ${width} l ${tail} 22 l -${tail} 22 h -${width} z"
          fill="${m.ribbon}" stroke="${m.plate}" stroke-width="1.5" stroke-opacity=".5" />
    <text x="${cx}" y="${cy + 10}" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif"
          font-size="${size}" font-weight="700" fill="${m.ribbonText}" textLength="${width - 34}"
          lengthAdjust="spacingAndGlyphs">${esc(text)}</text>`;
}

function circleAvatar(cx, cy, r, medal) {
  const m = MEDALS[medal];
  return `
    <circle cx="${cx}" cy="${cy}" r="${r + 15}" fill="none" stroke="${m.ring}" stroke-width="6" opacity=".85" />
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="#141419" stroke="${m.ring}" stroke-width="3" />
    <circle cx="${cx}" cy="${cy - r * 0.2}" r="${r * 0.33}" fill="#EDEDF0" />
    <path d="M ${cx - r * 0.6} ${cy + r * 0.66} q ${r * 0.6} ${-r * 0.95} ${r * 1.2} 0 z" fill="#EDEDF0" />`;
}

function crown(cx, cy, medal) {
  const m = MEDALS[medal];
  return `
    <path d="M ${cx - 38} ${cy + 14} l 5 -40 l 16 20 l 17 -27 l 17 27 l 16 -20 l 5 40 z"
          fill="${m.plate}" stroke="${m.ring}" stroke-width="2" />
    <text x="${cx}" y="${cy + 12}" text-anchor="middle" font-family="Georgia, serif" font-size="24"
          font-weight="700" fill="${m.ribbonText}">${m.label}</text>`;
}

function hoursPlate(cx, cy, medal, value) {
  const m = MEDALS[medal];
  return `
    <rect x="${cx - 118}" y="${cy}" width="236" height="66" rx="10" fill="#121217" stroke="${m.ring}" stroke-width="2" />
    <text x="${cx + 14}" y="${cy + 47}" text-anchor="end" font-family="Georgia, serif" font-size="42"
          font-weight="700" fill="${m.ring}">${esc(hoursText(value))}</text>
    <text x="${cx + 24}" y="${cy + 45}" text-anchor="start" font-family="Georgia, serif" font-size="21"
          letter-spacing="2" fill="#B9BCC6">HRS</text>`;
}

function plinth(cx, top, medal) {
  const m = MEDALS[medal];
  const heights = { 1: 96, 2: 74, 3: 64 };
  const h = heights[medal];
  return `
    <ellipse cx="${cx}" cy="${top}" rx="104" ry="15" fill="${m.ring}" opacity=".9" />
    <rect x="${cx - 104}" y="${top}" width="208" height="${h}" fill="#1B1B21" />
    <ellipse cx="${cx}" cy="${top + h}" rx="104" ry="15" fill="${m.ring}" opacity=".35" />`;
}

/**
 * One poster. `board` is a `weeks[].boards[]` entry straight from
 * GET /api/student-dashboard/leaderboard/weekly-tops, so whatever the endpoint
 * decided (podium order, tie-breaks, boards with no group set) is what prints.
 */
export function buildPosterSvg(board = {}) {
  const [line1, line2] = boardLines(board.batch, board.group);
  const week = weekLabel(board.weekStart, board.weekEnd);
  const byPlace = {};
  (board.top3 || []).forEach((t) => { byPlace[Number(t.place)] = t; });
  const cols = [
    { place: 2, cx: 268, cy: 786, r: 90 },
    { place: 1, cx: 540, cy: 712, r: 108 },
    { place: 3, cx: 812, cy: 800, r: 84 },
  ];

  const people = cols.map(({ place, cx, cy, r }) => {
    const row = byPlace[place] || {};
    return `
      ${crown(cx, cy - r - 26, place)}
      ${circleAvatar(cx, cy, r, place)}
      ${ribbon(cx, cy + r + 44, 244, place, displayName(row.studentName))}
      ${hoursPlate(cx, cy + r + 74, place, row.hours)}
      ${plinth(cx, cy + r + 156, place)}`;
  }).join('');

  const footer = BRAND.footer.map((t, i) => `
    <text x="${180 + i * 240}" y="1308" text-anchor="middle" font-family="Georgia, serif" font-size="17"
          fill="#CDD0D9" textLength="200" lengthAdjust="spacingAndGlyphs">${esc(t)}</text>`).join('');

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="Weekly Top 3, ${esc(line1)} ${esc(line2)}${week ? `, week ${esc(week)}` : ''}">
  <rect width="${W}" height="${H}" fill="${INK}" />
  <rect x="0" y="0" width="${W}" height="212" fill="#141319" />
  <rect x="0" y="210" width="${W}" height="2" fill="${GOLD_DARK}" opacity=".7" />
  <circle cx="540" cy="660" r="440" fill="#15141B" opacity=".7" />
  <g opacity=".18">
    <path d="M96 120 l20 34 l-36 -6 z" fill="${GOLD}" />
    <path d="M980 96 l24 30 l-38 2 z" fill="${GOLD}" />
    <path d="M150 1160 l22 32 l-38 0 z" fill="${GOLD}" />
    <path d="M930 1120 l18 36 l-36 -6 z" fill="${GOLD}" />
  </g>

  <g text-anchor="middle" font-family="Georgia, 'Times New Roman', serif">
    <text x="540" y="76" font-size="25" font-weight="700" fill="#F4F4F7" textLength="300"
          lengthAdjust="spacingAndGlyphs">${esc(BRAND.kicker)}</text>
    <text x="512" y="142" font-size="58" font-weight="700" fill="#F6F6F8" text-anchor="end">SUPER</text>
    <text x="528" y="142" font-size="58" font-weight="700" fill="${GOLD}" text-anchor="start">75</text>
    <text x="540" y="182" font-size="18" fill="#A7AAB4" textLength="560"
          lengthAdjust="spacingAndGlyphs">${esc(BRAND.tagline)}</text>
    <path d="M540 198 l12 20 l-24 0 z" fill="${GOLD}" />

    <text x="540" y="318" font-size="64" font-weight="700" fill="#F6F6F8" textLength="700"
          lengthAdjust="spacingAndGlyphs">WEEKLY</text>
    <text x="540" y="446" font-size="110" font-weight="700" fill="${GOLD}" textLength="760"
          lengthAdjust="spacingAndGlyphs">TOP 3</text>
    <path d="M332 470 h416 l-24 38 h-368 z" fill="${GOLD}" />
    <text x="540" y="498" font-size="26" font-weight="700" fill="#241C04" textLength="360"
          lengthAdjust="spacingAndGlyphs">TOP PERFORMERS</text>
  </g>

  <g font-family="Georgia, serif" fill="#7F828C" font-style="italic" font-size="23">
    ${BRAND.notesLeft.map((t, i) => `<text x="66" y="${470 + i * 34}">${esc(t)}</text>`).join('')}
    ${BRAND.notesRight.map((t, i) => `<text x="1014" y="${470 + i * 34}" text-anchor="end">${esc(t)}</text>`).join('')}
  </g>

  <g>
    <rect x="834" y="222" width="224" height="96" rx="4" fill="#EAE4D3" stroke="#C6BBA0" stroke-width="2" />
    <text x="946" y="264" text-anchor="middle" font-family="Georgia, serif" font-size="29" font-weight="700"
          fill="#22201A" textLength="176" lengthAdjust="spacingAndGlyphs">${esc(line1)}</text>
    <text x="946" y="302" text-anchor="middle" font-family="Georgia, serif" font-size="29" font-weight="700"
          fill="#22201A" textLength="176" lengthAdjust="spacingAndGlyphs">${esc(line2)}</text>
  </g>

  <g font-family="Georgia, 'Times New Roman', serif">${people}</g>

  <!-- the cursive stack is a bonus, italic serif is the floor: whatever the
       machine has, the signature still reads as a signature -->
  <text x="540" y="1206" text-anchor="middle" font-style="italic"
        font-family="'Segoe Script','Bradley Hand','Brush Script MT',cursive"
        font-size="68" font-weight="700" fill="${GOLD_LIGHT}">${esc(BRAND.closer)}</text>
  <text x="540" y="1248" text-anchor="middle" font-family="Georgia, serif" font-size="23" fill="#C7CAD3"
        textLength="420" lengthAdjust="spacingAndGlyphs"${week ? '' : ' opacity="0"'}>WEEK ${esc(week || '—')}</text>
  <line x1="60" y1="1268" x2="1020" y2="1268" stroke="#34343D" stroke-width="1" />
  ${footer}
</svg>`;
}

/** PNG for WhatsApp, drawn by the browser — no upload, no third party. */
export async function posterPngDataUrl(svg, width = W, height = H) {
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error('poster could not be rasterised'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = INK;
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    return canvas.toDataURL('image/png');
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The text that goes with the image in the group. */
export function posterCaption(board = {}) {
  const [line1, line2] = boardLines(board.batch, board.group);
  const week = weekLabel(board.weekStart, board.weekEnd);
  const byPlace = {};
  (board.top3 || []).forEach((t) => { byPlace[Number(t.place)] = t; });
  const names = [1, 2, 3]
    .filter((place) => byPlace[place])
    .map((place) => `${['🥇', '🥈', '🥉'][place - 1]} ${byPlace[place].studentName} — ${hoursText(byPlace[place].hours)} hrs`)
    .join('\n');
  return `${BRAND.kicker} ${BRAND.name} · Weekly Top 3\n${line1} · ${line2}${week ? ` · ${week}` : ''}\n\n${names}\n\n${BRAND.duty}\n\n${BRAND.closer}`;
}
