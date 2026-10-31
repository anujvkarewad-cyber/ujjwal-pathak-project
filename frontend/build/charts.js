/**
 * SVG charts — no external library, pure SVG generation.
 * Functions return SVG strings that can be inserted into HTML.
 */
"use strict";

/* ===================== BAR CHART ===================== */
function barChart(data, opts) {
  opts = opts || {};
  const W = opts.width || 500;
  const H = opts.height || 200;
  const pad = { top: 10, right: 10, bottom: 30, left: 35 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;
  if (!data || !data.length) return '<div class="empty">No data</div>';
  const max = Math.max.apply(null, data.map((d) => d.value)) || 1;
  const bw = cw / data.length * 0.6;
  const gap = cw / data.length * 0.4;
  const colors = opts.colors || ["#4F46E5", "#16A34A", "#D97706", "#DC2626", "#0284C7", "#7C3AED", "#DB2777"];
  const gridLines = 4;
  let grid = "";
  for (let i = 0; i <= gridLines; i++) {
    const y = pad.top + ch - (ch * i / gridLines);
    const val = Math.round(max * i / gridLines);
    grid += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '" stroke="#E5E7EB" stroke-width="1"/>';
    grid += '<text x="' + (pad.left - 4) + '" y="' + (y + 3) + '" text-anchor="end" font-size="9" fill="#9CA3AF">' + val + '</text>';
  }
  let bars = "";
  data.forEach((d, i) => {
    const bh = (d.value / max) * ch;
    const x = pad.left + i * (bw + gap) + gap / 2;
    const y = pad.top + ch - bh;
    const color = d.color || colors[i % colors.length];
    bars += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + bh + '" rx="3" fill="' + color + '"><title>' + esc(d.label) + ': ' + d.value + '</title></rect>';
    bars += '<text x="' + (x + bw / 2) + '" y="' + (H - pad.bottom + 14) + '" text-anchor="middle" font-size="9" fill="#6B7280">' + esc((d.label || "").slice(0, 8)) + '</text>';
    if (opts.showValues) {
      bars += '<text x="' + (x + bw / 2) + '" y="' + (y - 3) + '" text-anchor="middle" font-size="9" fill="#374151" font-weight="600">' + d.value + '</text>';
    }
  });
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto">' + grid + bars + '</svg>';
}

/* ===================== LINE / AREA CHART ===================== */
function lineChart(data, opts) {
  opts = opts || {};
  const W = opts.width || 500;
  const H = opts.height || 200;
  const pad = { top: 10, right: 10, bottom: 30, left: 35 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;
  if (!data || !data.length) return '<div class="empty">No data</div>';
  const max = Math.max.apply(null, data.map((d) => d.value)) || 1;
  const min = opts.min != null ? opts.min : 0;
  const range = max - min || 1;
  const step = cw / Math.max(1, data.length - 1);
  const points = data.map((d, i) => ({ x: pad.left + i * step, y: pad.top + ch - ((d.value - min) / range) * ch, d: d }));
  const linePath = points.map((p, i) => (i === 0 ? "M" : "L") + p.x + " " + p.y).join(" ");
  const areaPath = linePath + " L" + points[points.length - 1].x + " " + (pad.top + ch) + " L" + points[0].x + " " + (pad.top + ch) + " Z";
  const color = opts.color || "#4F46E5";
  const gridLines = 4;
  let grid = "";
  for (let i = 0; i <= gridLines; i++) {
    const y = pad.top + ch - (ch * i / gridLines);
    const val = Math.round(max * i / gridLines);
    grid += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '" stroke="#E5E7EB" stroke-width="1"/>';
    grid += '<text x="' + (pad.left - 4) + '" y="' + (y + 3) + '" text-anchor="end" font-size="9" fill="#9CA3AF">' + val + '</text>';
  }
  let dots = "";
  points.forEach((p) => {
    dots += '<circle cx="' + p.x + '" cy="' + p.y + '" r="3" fill="' + color + '"><title>' + esc(p.d.label) + ': ' + p.d.value + '</title></circle>';
  });
  let labels = "";
  const labelStep = Math.ceil(data.length / 6);
  data.forEach((d, i) => {
    if (i % labelStep === 0) {
      labels += '<text x="' + points[i].x + '" y="' + (H - pad.bottom + 14) + '" text-anchor="middle" font-size="9" fill="#6B7280">' + esc((d.label || "").slice(0, 8)) + '</text>';
    }
  });
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto">' + grid + '<path d="' + areaPath + '" fill="' + color + '" fill-opacity="0.1"/><path d="' + linePath + '" fill="none" stroke="' + color + '" stroke-width="2"/>' + dots + labels + '</svg>';
}

/* ===================== PIE CHART ===================== */
function pieChart(data, opts) {
  opts = opts || {};
  const size = opts.size || 180;
  const cx = size / 2, cy = size / 2, r = size / 2 - 5;
  if (!data || !data.length) return '<div class="empty">No data</div>';
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const colors = opts.colors || ["#4F46E5", "#16A34A", "#D97706", "#DC2626", "#0284C7", "#7C3AED", "#DB2777", "#94A3B8"];
  let slices = "";
  let angle = -Math.PI / 2;
  data.forEach((d, i) => {
    const sliceAngle = (d.value / total) * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sliceAngle);
    const y2 = cy + r * Math.sin(angle + sliceAngle);
    const largeArc = sliceAngle > Math.PI ? 1 : 0;
    const color = d.color || colors[i % colors.length];
    if (sliceAngle >= Math.PI * 2 - 0.001) {
      slices += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + color + '"><title>' + esc(d.label) + ': ' + d.value + '</title></circle>';
    } else {
      slices += '<path d="M' + cx + ' ' + cy + ' L' + x1 + ' ' + y1 + ' A' + r + ' ' + r + ' 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 + ' Z" fill="' + color + '"><title>' + esc(d.label) + ': ' + d.value + '</title></path>';
    }
    angle += sliceAngle;
  });
  const legend = data.map((d, i) => {
    const color = d.color || colors[i % colors.length];
    return '<div style="display:flex;align-items:center;gap:5px;font-size:11px"><span style="width:9px;height:9px;border-radius:2px;background:' + color + '"></span>' + esc(d.label) + ' (' + Math.round(d.value / total * 100) + '%)</div>';
  }).join("");
  return '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap"><svg viewBox="0 0 ' + size + ' ' + size + '" style="width:' + size + 'px;height:' + size + 'px">' + slices + '</svg><div style="display:flex;flex-direction:column;gap:4px">' + legend + '</div></div>';
}

/* ===================== HEATMAP ===================== */
function heatmap(rows, cols, cellMap, opts) {
  opts = opts || {};
  if (!rows || !rows.length || !cols || !cols.length) return '<div class="empty">No data</div>';
  const cellW = 28, cellH = 28, gap = 2;
  const labelW = 100, labelH = 20;
  const W = labelW + cols.length * (cellW + gap) + 10;
  const H = labelH + rows.length * (cellH + gap) + 10;
  const colorMap = { Weak: "#DC2626", Medium: "#D97706", Strong: "#4F46E5", Mastered: "#16A34A", "Not assessed": "#E5E7EB" };
  let grid = "";
  cols.forEach((c, i) => {
    grid += '<text x="' + (labelW + i * (cellW + gap) + cellW / 2) + '" y="' + (labelH - 4) + '" text-anchor="middle" font-size="8" fill="#9CA3AF" transform="rotate(-45 ' + (labelW + i * (cellW + gap) + cellW / 2) + ' ' + (labelH - 4) + ')">' + esc((c.label || c).slice(0, 8)) + '</text>';
  });
  rows.forEach((r, ri) => {
    grid += '<text x="' + (labelW - 4) + '" y="' + (labelH + ri * (cellH + gap) + cellH / 2 + 3) + '" text-anchor="end" font-size="9" fill="#6B7280">' + esc(r.label || r) + '</text>';
    cols.forEach((c, ci) => {
      const key = (typeof r === "object" ? r.id : r) + "|" + (typeof c === "object" ? c.id : c);
      const cell = cellMap[key];
      const color = cell ? (colorMap[cell.band] || "#E5E7EB") : "#F9FAFB";
      const title = cell ? (r.label + " · " + c.label + ": " + cell.band) : "No data";
      grid += '<rect x="' + (labelW + ci * (cellW + gap)) + '" y="' + (labelH + ri * (cellH + gap)) + '" width="' + cellW + '" height="' + cellH + '" rx="3" fill="' + color + '" stroke="#E5E7EB"><title>' + esc(title) + '</title></rect>';
    });
  });
  return '<div style="overflow:auto"><svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;min-width:' + W + 'px">' + grid + '</svg></div>';
}

/* ===================== DOUGHNUT CHART ===================== */
function doughnutChart(data, opts) {
  opts = opts || {};
  const size = opts.size || 160;
  const cx = size / 2, cy = size / 2, rOuter = size / 2 - 5, rInner = rOuter * 0.6;
  if (!data || !data.length) return '<div class="empty">No data</div>';
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const colors = opts.colors || ["#4F46E5", "#16A34A", "#D97706", "#DC2626", "#0284C7", "#7C3AED", "#DB2777"];
  let slices = "";
  let angle = -Math.PI / 2;
  data.forEach((d, i) => {
    const sliceAngle = (d.value / total) * Math.PI * 2;
    const color = d.color || colors[i % colors.length];
    const x1o = cx + rOuter * Math.cos(angle);
    const y1o = cy + rOuter * Math.sin(angle);
    const x2o = cx + rOuter * Math.cos(angle + sliceAngle);
    const y2o = cy + rOuter * Math.sin(angle + sliceAngle);
    const x1i = cx + rInner * Math.cos(angle + sliceAngle);
    const y1i = cy + rInner * Math.sin(angle + sliceAngle);
    const x2i = cx + rInner * Math.cos(angle);
    const y2i = cy + rInner * Math.sin(angle);
    const largeArc = sliceAngle > Math.PI ? 1 : 0;
    slices += '<path d="M' + x1o + ' ' + y1o + ' A' + rOuter + ' ' + rOuter + ' 0 ' + largeArc + ' 1 ' + x2o + ' ' + y2o + ' L' + x1i + ' ' + y1i + ' A' + rInner + ' ' + rInner + ' 0 ' + largeArc + ' 0 ' + x2i + ' ' + y2i + ' Z" fill="' + color + '"><title>' + esc(d.label) + ': ' + d.value + '</title></path>';
    angle += sliceAngle;
  });
  const legend = data.map((d, i) => {
    const color = d.color || colors[i % colors.length];
    return '<div style="display:flex;align-items:center;gap:5px;font-size:11px"><span style="width:9px;height:9px;border-radius:2px;background:' + color + '"></span>' + esc(d.label) + ' (' + Math.round(d.value / total * 100) + '%)</div>';
  }).join("");
  return '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap"><svg viewBox="0 0 ' + size + ' ' + size + '" style="width:' + size + 'px;height:' + size + 'px">' + slices + '</svg><div style="display:flex;flex-direction:column;gap:4px">' + legend + '</div></div>';
}

/* ===================== COMPOSED CHART (bar + line) ===================== */
function composedChart(barData, lineData, opts) {
  opts = opts || {};
  const W = opts.width || 500;
  const H = opts.height || 220;
  const pad = { top: 10, right: 10, bottom: 30, left: 35 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;
  if (!barData || !barData.length) return '<div class="empty">No data</div>';
  const maxBar = Math.max.apply(null, barData.map((d) => d.value)) || 1;
  const maxLine = lineData && lineData.length ? Math.max.apply(null, lineData.map((d) => d.value)) : maxBar;
  const max = Math.max(maxBar, maxLine) || 1;
  const step = cw / Math.max(1, barData.length - 1);
  const bw = cw / barData.length * 0.5;
  const gridLines = 4;
  let grid = "";
  for (let i = 0; i <= gridLines; i++) {
    const y = pad.top + ch - (ch * i / gridLines);
    grid += '<line x1="' + pad.left + '" y1="' + y + '" x2="' + (W - pad.right) + '" y2="' + y + '" stroke="#E5E7EB" stroke-width="1"/>';
    grid += '<text x="' + (pad.left - 4) + '" y="' + (y + 3) + '" text-anchor="end" font-size="9" fill="#9CA3AF">' + Math.round(max * i / gridLines) + '</text>';
  }
  let bars = "";
  barData.forEach((d, i) => {
    const bh = (d.value / max) * ch;
    const x = pad.left + i * step + (step - bw) / 2;
    bars += '<rect x="' + x + '" y="' + (pad.top + ch - bh) + '" width="' + bw + '" height="' + bh + '" rx="3" fill="' + (d.color || "#4F46E5") + '"><title>' + esc(d.label) + ': ' + d.value + '</title></rect>';
  });
  let line = "";
  if (lineData && lineData.length) {
    const points = lineData.map((d, i) => ({ x: pad.left + i * step, y: pad.top + ch - (d.value / max) * ch, d: d }));
    const path = points.map((p, i) => (i === 0 ? "M" : "L") + p.x + " " + p.y).join(" ");
    line = '<path d="' + path + '" fill="none" stroke="#16A34A" stroke-width="2"/>';
    points.forEach((p) => { line += '<circle cx="' + p.x + '" cy="' + p.y + '" r="3" fill="#16A34A"><title>' + esc(p.d.label) + ': ' + p.d.value + '</title></circle>'; });
  }
  let labels = "";
  const labelStep = Math.ceil(barData.length / 6);
  barData.forEach((d, i) => {
    if (i % labelStep === 0) {
      labels += '<text x="' + (pad.left + i * step) + '" y="' + (H - pad.bottom + 14) + '" text-anchor="middle" font-size="9" fill="#6B7280">' + esc((d.label || "").slice(0, 8)) + '</text>';
    }
  });
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto">' + grid + bars + line + labels + '</svg>';
}

window.UMP_CHARTS = { barChart, lineChart, pieChart, doughnutChart, heatmap, composedChart };
