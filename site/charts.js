// Chart module. Every color is read from a CSS token at draw time, so charts follow the theme.
// Every value comes from generated data passed in by app.js.
const active = new Set();

export const LABEL_TOKEN = {
  'Specific Praise': '--praise', 'Generic Good': '--good', 'Feature Request': '--request',
  'Generic Bad': '--bad', 'Nonsense': '--nonsense', 'Specific Complaint': '--complaint',
};
// Fixed order: validated for color separation in both themes. Do not reorder.
export const LABEL_ORDER = Object.keys(LABEL_TOKEN);
export const colorForLabel = label => LABEL_TOKEN[label] || '--neutral';

const css = token => getComputedStyle(document.documentElement).getPropertyValue(token).trim();
const fade = (color, amount) => { const hex = color.replace('#', ''); const [r, g, b] = [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)); return Number.isNaN(r + g + b) ? color : `rgba(${r}, ${g}, ${b}, ${amount})`; };
const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
const int = value => value === null || value === undefined ? 'n/a' : Math.round(value).toLocaleString('en-US');
const dec = (value, digits = 2) => value === null || value === undefined ? 'n/a' : value.toFixed(digits);
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const sans = () => getComputedStyle(document.body).fontFamily;
const mono = () => css('--font-mono') || 'monospace';

export function clearCharts() { for (const entry of active) entry.chart?.destroy(); active.clear(); }
export function redrawCharts() { for (const entry of active) render(entry, false); }

/* ---------- shared pieces ---------- */

function theme() {
  return {text1: css('--text-1'), text2: css('--text-2'), text3: css('--text-3'), border: css('--border'), surface: css('--surface'), raised: css('--raised')};
}
function tick(t) { return {color: t.text3, font: {family: mono(), size: 11}}; }
// linked: the row labels are links (see chartCard), so they take the link color.
function catTick(t, linked = false) { return {color: linked ? css('--brand') : t.text2, font: {family: sans(), size: 12, weight: linked ? '500' : '400'}, autoSkip: false}; }
function tooltip(t, callbacks) {
  return {backgroundColor: t.raised, titleColor: t.text1, bodyColor: t.text2, footerColor: t.text3, borderColor: t.border, borderWidth: 1,
    padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true,
    titleFont: {family: sans(), size: 12, weight: '600'}, bodyFont: {family: mono(), size: 12}, footerFont: {family: sans(), size: 11, weight: '400'}, callbacks};
}
function legend(t, display = true) {
  return {display, position: 'top', align: 'start', labels: {color: t.text3, usePointStyle: true, pointStyle: 'circle', boxWidth: 7, boxHeight: 7, padding: 14, font: {family: sans(), size: 12}}};
}
function base(t, extra = {}) {
  return {responsive: true, maintainAspectRatio: false,
    animation: reducedMotion() ? false : {duration: 400, easing: 'easeOutQuart'},
    interaction: {mode: 'index', intersect: false}, ...extra};
}
const wrapLabel = (label, width = 22) => {
  if (typeof label !== 'string' || label.length <= width) return label;
  const lines = []; let line = '';
  for (const word of label.split(' ')) { if (line && `${line} ${word}`.length > width) { lines.push(line); line = word; } else line = line ? `${line} ${word}` : word; }
  if (line) lines.push(line); return lines;
};

// Draws a value at the data end of each horizontal bar (or the stack total).
const endLabels = (t, format, {stackTotal = false, diverging = null} = {}) => ({id: 'endLabels', afterDatasetsDraw(chart) {
  const ctx = chart.ctx; ctx.save(); ctx.font = `500 12px ${mono()}`; ctx.fillStyle = t.text1; ctx.textBaseline = 'middle';
  const count = chart.data.labels.length;
  for (let index = 0; index < count; index += 1) {
    if (stackTotal) {
      let total = 0, x = chart.scales.x.getPixelForValue(0), y = null;
      chart.data.datasets.forEach((set, d) => { const meta = chart.getDatasetMeta(d); if (meta.hidden) return; total += set.data[index] || 0; const bar = meta.data[index]; if (bar) { x = Math.max(x, bar.x); y = bar.y; } });
      if (y !== null) { ctx.textAlign = 'left'; ctx.fillText(format(total, index), x + 8, y); }
    } else {
      const bar = chart.getDatasetMeta(0).data[index]; const raw = chart.data.datasets[0].data[index];
      if (!bar || raw === null || raw === undefined) continue;
      const value = Array.isArray(raw) ? raw[1] : raw;
      const left = diverging !== null && value < diverging;
      ctx.textAlign = left ? 'right' : 'left';
      // A bar that runs left of the center gets its value on the empty right side, clear of the axis labels.
      if (left) ctx.textAlign = 'left';
      const x = Math.max(bar.x, bar.base) + 8;
      ctx.fillText(format(value, index), x, bar.y);
    }
  }
  ctx.restore();
}});

/* ---------- chart builders: each returns a Chart.js config ---------- */

export const builders = {
  // Bars on the left axis, two lines on the right axis fixed at 1 to 5.
  combo({labels, volume, stars, sentiment}) {
    const t = theme(), cStars = css('--stars'), cSent = css('--sentiment');
    return {type: 'bar', data: {labels, datasets: [
      {type: 'line', label: 'Average stars', data: stars, yAxisID: 'rating', borderColor: cStars, backgroundColor: cStars, borderWidth: 2.5, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: t.surface, pointBorderWidth: 2, tension: 0.25, order: 1},
      {type: 'line', label: 'Average sentiment', data: sentiment, yAxisID: 'rating', borderColor: cSent, backgroundColor: cSent, borderWidth: 2.5, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: t.surface, pointBorderWidth: 2, tension: 0.25, order: 2},
      {type: 'bar', label: 'Reviews', data: volume, yAxisID: 'volume', backgroundColor: fade(css('--volume'), 0.38), hoverBackgroundColor: fade(css('--volume'), 0.6), borderRadius: {topLeft: 4, topRight: 4}, maxBarThickness: 56, order: 3},
    ]}, options: base(t, {scales: {
      x: {grid: {display: false}, ticks: tick(t), border: {color: t.border}},
      volume: {position: 'left', beginAtZero: true, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), callback: v => int(v)}, title: {display: true, text: 'Reviews', color: t.text3, font: {family: sans(), size: 11}}},
      rating: {position: 'right', min: 1, max: 5, grid: {display: false}, border: {display: false}, ticks: {...tick(t), color: cStars, stepSize: 1, callback: v => v.toFixed(1)}, title: {display: true, text: 'Average, 1 to 5', color: t.text3, font: {family: sans(), size: 11}}},
    }, plugins: {legend: legend(t), tooltip: tooltip(t, {label: c => ` ${c.dataset.label}: ${c.dataset.yAxisID === 'rating' ? dec(c.parsed.y) : int(c.parsed.y)}`})}})};
  },

  // steps: [{name, start, end, token, strength, value, sign, link}]
  waterfall({steps}) {
    const t = theme();
    const connectors = {id: 'connectors', afterDatasetsDraw(chart) {
      const meta = chart.getDatasetMeta(0), ctx = chart.ctx; ctx.save(); ctx.strokeStyle = t.text3; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      steps.forEach((step, i) => { const next = steps[i + 1]; if (!next || step.link === undefined) return;
        const a = meta.data[i], b = meta.data[i + 1]; const y = chart.scales.y.getPixelForValue(step.link);
        ctx.beginPath(); ctx.moveTo(a.x + a.width / 2, y); ctx.lineTo(b.x - b.width / 2, y); ctx.stroke(); });
      ctx.setLineDash([]); ctx.font = `500 12px ${mono()}`; ctx.fillStyle = t.text1; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      steps.forEach((step, i) => { const bar = meta.data[i]; const top = chart.scales.y.getPixelForValue(Math.max(step.start, step.end)); ctx.fillText(`${step.sign || ''}${int(step.value)}`, bar.x, top - 6); });
      ctx.restore();
    }};
    return {type: 'bar', plugins: [connectors], data: {labels: steps.map(s => wrapLabel(s.name, 12)), datasets: [{label: 'Reviews', data: steps.map(s => [s.start, s.end]),
      backgroundColor: steps.map(s => fade(css(s.token), s.strength)), borderRadius: 4, borderSkipped: false, maxBarThickness: 84}]},
    options: base(t, {layout: {padding: {top: 22}}, scales: {x: {grid: {display: false}, ticks: catTick(t), border: {color: t.border}},
      y: {beginAtZero: true, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), callback: v => int(v)}}},
      plugins: {legend: {display: false}, tooltip: tooltip(t, {title: items => steps[items[0].dataIndex].name, label: c => ` ${steps[c.dataIndex].sign || ''}${int(steps[c.dataIndex].value)} reviews`})}})};
  },

  // segments: [{name, value, token}]
  donut({segments, center, caption}) {
    const t = theme(), total = segments.reduce((sum, s) => sum + s.value, 0);
    const middle = {id: 'middle', afterDraw(chart) {
      const {ctx, chartArea: a} = chart; const x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2; ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = t.text1; ctx.font = `500 24px ${mono()}`; ctx.fillText(center, x, y - 7);
      ctx.fillStyle = t.text3; ctx.font = `12px ${sans()}`; ctx.fillText(caption, x, y + 15); ctx.restore();
    }};
    return {type: 'doughnut', plugins: [middle], data: {labels: segments.map(s => s.name), datasets: [{data: segments.map(s => s.value),
      backgroundColor: segments.map(s => css(s.token)), borderColor: t.surface, borderWidth: 2, hoverOffset: 4}]},
    options: base(t, {cutout: '68%', interaction: {mode: 'nearest', intersect: true}, plugins: {legend: {display: false},
      tooltip: tooltip(t, {label: c => ` ${c.label}: ${int(c.parsed)} (${total ? Math.round(c.parsed / total * 100) : 0}%)`})}})};
  },

  // series: [{name, token, values}]
  groupedBars({labels, series}) {
    const t = theme();
    return {type: 'bar', data: {labels, datasets: series.map(s => ({label: s.name, data: s.values, backgroundColor: css(s.token), borderRadius: {topLeft: 4, topRight: 4}, maxBarThickness: 34}))},
      options: base(t, {scales: {x: {grid: {display: false}, ticks: tick(t), border: {color: t.border}}, y: {beginAtZero: true, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), callback: v => int(v)}}},
        plugins: {legend: legend(t), tooltip: tooltip(t, {title: items => `${items[0].label} out of 5`, label: c => ` ${c.dataset.label}: ${int(c.parsed.y)}`})}})};
  },

  // Horizontal stack. series: [{name, token, values}]. percent: values are shares of 100.
  stackedBars({labels, series, percent = false, faded = [], totals = true, notes = [], linked = false}) {
    const t = theme();
    const plugins = totals && !percent ? [endLabels(t, v => int(v), {stackTotal: true})] : [];
    return {type: 'bar', plugins, data: {labels: labels.map(l => wrapLabel(l)), datasets: series.map(s => ({label: s.name, data: s.values,
      backgroundColor: labels.map((_, i) => fade(css(s.token), faded[i] ? 0.45 : 1)), borderColor: t.surface, borderWidth: {left: 0, right: 2, top: 0, bottom: 0}, borderRadius: 3, borderSkipped: false, maxBarThickness: 26}))},
    options: base(t, {indexAxis: 'y', layout: {padding: {right: totals && !percent ? 52 : 4}}, scales: {
      x: {stacked: true, beginAtZero: true, max: percent ? 100 : undefined, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), callback: v => percent ? `${v}%` : int(v)}},
      y: {stacked: true, grid: {display: false}, border: {display: false}, ticks: catTick(t, linked)}},
      plugins: {legend: legend(t), tooltip: tooltip(t, {label: c => ` ${c.dataset.label}: ${percent ? `${dec(c.parsed.x, 1)}%` : int(c.parsed.x)}`, footer: items => notes[items[0].dataIndex] || ''})}})};
  },

  // Single-series horizontal bars. tokens: one token or one per bar.
  bars({labels, values, token = '--accent', tokens, percent = false, faded = [], notes = []}) {
    const t = theme();
    return {type: 'bar', plugins: [endLabels(t, v => percent ? `${Math.round(v)}%` : int(v))], data: {labels: labels.map(l => wrapLabel(l)), datasets: [{label: 'Reviews', data: values,
      backgroundColor: labels.map((_, i) => fade(css(tokens ? tokens[i] : token), faded[i] ? 0.45 : 1)), borderRadius: 4, borderSkipped: 'start', maxBarThickness: 24}]},
    options: base(t, {indexAxis: 'y', layout: {padding: {right: 52}}, scales: {
      x: {beginAtZero: true, max: percent ? 100 : undefined, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), callback: v => percent ? `${v}%` : int(v)}},
      y: {grid: {display: false}, border: {display: false}, ticks: catTick(t)}},
      plugins: {legend: {display: false}, tooltip: tooltip(t, {label: c => ` ${percent ? `${dec(c.parsed.x, 1)}%` : int(c.parsed.x)}`, footer: items => notes[items[0].dataIndex] || ''})}})};
  },

  // Bars growing left or right from a center value.
  diverging({labels, values, center, faded = [], notes = [], linked = false}) {
    const t = theme(), up = css('--praise'), down = css('--complaint');
    const centerLine = {id: 'centerLine', afterDatasetsDraw(chart) { const x = chart.scales.x.getPixelForValue(center), a = chart.chartArea, ctx = chart.ctx; ctx.save(); ctx.strokeStyle = t.text3; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, a.top); ctx.lineTo(x, a.bottom); ctx.stroke(); ctx.restore(); }};
    return {type: 'bar', plugins: [centerLine, endLabels(t, v => dec(v), {diverging: center})], data: {labels: labels.map(l => wrapLabel(l)), datasets: [{label: 'Mean stars', data: values.map(v => v === null ? null : [center, v]),
      backgroundColor: values.map((v, i) => fade(v >= center ? up : down, faded[i] ? 0.45 : 1)), borderRadius: 4, borderSkipped: false, maxBarThickness: 22}]},
    options: base(t, {indexAxis: 'y', layout: {padding: {right: 44, left: 4}}, scales: {
      x: {min: 1, max: 5, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), stepSize: 1, callback: v => v.toFixed(1)}},
      y: {grid: {display: false}, border: {display: false}, ticks: catTick(t, linked)}},
      plugins: {legend: {display: false}, tooltip: tooltip(t, {label: c => ` Mean stars: ${dec(values[c.dataIndex])}`, footer: items => notes[items[0].dataIndex] || ''})}})};
  },

  // Line with optional fill and point sizes.
  line({labels, values, token, fill = false, min, max, radii, name, notes = [], digits = 0}) {
    const t = theme(), color = css(token);
    return {type: 'line', data: {labels, datasets: [{label: name, data: values, borderColor: color, backgroundColor: fill ? fade(color, 0.22) : color, fill, borderWidth: 2,
      pointRadius: radii || 3, pointHoverRadius: radii ? radii.map(r => r + 2) : 5, pointBackgroundColor: color, pointBorderColor: t.surface, pointBorderWidth: 2, tension: 0.25}]},
    options: base(t, {scales: {x: {grid: {display: false}, ticks: tick(t), border: {color: t.border}},
      y: {min, max, beginAtZero: min === undefined, grid: {color: fade(t.border, 0.7)}, border: {display: false}, ticks: {...tick(t), stepSize: digits ? 0.5 : undefined, precision: digits ? undefined : 0, callback: v => digits ? v.toFixed(1) : int(v)}}},
      plugins: {legend: {display: false}, tooltip: tooltip(t, {label: c => ` ${name}: ${digits ? dec(c.parsed.y) : int(c.parsed.y)}`, footer: items => notes[items[0].dataIndex] || ''})}})};
  },

  // points: [{id, name, short, x, y, type}]. x on a log scale so small items separate.
  matrix({points, medianX, medianY, onPick}) {
    const t = theme(), fix = css('--complaint'), explore = css('--request');
    const biggest = Math.max(...points.map(p => p.x));
    // Kept small on purpose: the crowded left side has items only a few reviews apart.
    const radius = p => 5 + 14 * Math.sqrt(p.x / biggest);
    const lowest = Math.min(...points.map(p => p.y)), highest = Math.max(...points.map(p => p.y)), smallest = Math.min(...points.map(p => p.x));
    // The y range gets a band above the highest and below the lowest bubble. The corner headings live in those bands.
    const spanY = Math.max(20, highest - lowest), yMax = highest + spanY * 0.34, yMin = lowest - spanY * 0.34;
    // Quadrants: which side of the median size and the median pain each area falls on.
    const QUADS = [
      {key: 'tr', big: true, hot: true, title: 'Big and painful', note: 'Many reviews, mostly 1 to 2 stars. Fix first'},
      {key: 'tl', big: false, hot: true, title: 'Small but severe', note: 'Few reviews, mostly 1 to 2 stars. Cheap, loud, usually operational'},
      {key: 'br', big: true, hot: false, title: 'Big, milder', note: 'Many reviews, mixed stars. Product and pricing questions'},
      {key: 'bl', big: false, hot: false, title: 'Small, milder', note: 'Few reviews, mixed stars. Watch'},
    ];
    const inQuad = q => points.filter(p => (p.x >= medianX) === q.big && (p.y >= medianY) === q.hot).length;
    // Items with near-identical values would sit on top of each other. Push overlapping bubbles
    // apart by the smallest amount that separates them; tooltips and the table keep exact values.
    const separate = chart => {
      const a = chart.chartArea, els = []; chart.data.datasets.forEach((set, d) => chart.getDatasetMeta(d).data.forEach((el, i) => els.push({el, r: set.data[i].r})));
      const pad = 3;
      for (let pass = 0; pass < 60; pass += 1) {
        let moved = false;
        for (let i = 0; i < els.length; i += 1) for (let j = i + 1; j < els.length; j += 1) {
          const p = els[i], q = els[j]; let dx = q.el.x - p.el.x, dy = q.el.y - p.el.y; let dist = Math.hypot(dx, dy);
          const need = p.r + q.r + pad; if (dist >= need) continue;
          if (dist < 0.01) { dx = Math.cos(i + j); dy = Math.sin(i + j); dist = 1; }
          const push = (need - dist) / 2, ux = dx / dist, uy = dy / dist;
          p.el.x -= ux * push; p.el.y -= uy * push; q.el.x += ux * push; q.el.y += uy * push; moved = true;
        }
        for (const {el, r} of els) { el.x = Math.min(a.right - r, Math.max(a.left + r, el.x)); el.y = Math.min(a.bottom - r, Math.max(a.top + r, el.y)); }
        if (!moved) break;
      }
    };
    const decorate = {id: 'decorate', beforeDatasetsDraw(chart) {
      separate(chart);
      const {ctx, chartArea: a, scales} = chart; const x = scales.x.getPixelForValue(medianX), y = scales.y.getPixelForValue(medianY);
      ctx.save();
      // A tint per quadrant, strongest where an area is both big and painful.
      const tint = {tr: fade(fix, 0.10), tl: fade(fix, 0.04), br: fade(explore, 0.05), bl: null};
      for (const q of QUADS) {
        if (!tint[q.key]) continue;
        const l = q.big ? x : a.left, r = q.big ? a.right : x, top = q.hot ? a.top : y, bottom = q.hot ? y : a.bottom;
        ctx.fillStyle = tint[q.key]; ctx.fillRect(l, top, r - l, bottom - top);
      }
      // Solid median lines, each named where it meets the plot edge.
      ctx.strokeStyle = t.text2; ctx.globalAlpha = 0.7; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, a.top); ctx.lineTo(x, a.bottom); ctx.moveTo(a.left, y); ctx.lineTo(a.right, y); ctx.stroke(); ctx.globalAlpha = 1;
      const boxes = [];
      const write = (text, px, py, align, baseline, font, color) => {
        ctx.font = font; ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = baseline; ctx.fillText(text, px, py);
        const w = ctx.measureText(text).width, l = align === 'left' ? px : align === 'right' ? px - w : px - w / 2, top = baseline === 'top' ? py : py - 14;
        boxes.push({l: l - 4, r: l + w + 4, t: top - 2, b: top + 20, own: null});
      };
      // Corner labels: the quadrant's name, how many areas sit in it, and what the position means.
      for (const q of QUADS) {
        const count = inQuad(q), px = q.big ? a.right - 10 : a.left + 10, align = q.big ? 'right' : 'left';
        const head = `${q.title} · ${count} ${count === 1 ? 'area' : 'areas'}`;
        const titleY = q.hot ? a.top + 8 : a.bottom - 44, noteY = titleY + 21;
        write(head, px, titleY, align, 'top', `700 16px ${sans()}`, css('--brand'));
        write(q.note, px, noteY, align, 'top', `500 11.5px ${sans()}`, t.text2);
      }
      chart.$quadBoxes = boxes; ctx.restore();
    }, afterDatasetsDraw(chart) {
      const {ctx, chartArea: a} = chart; ctx.save(); ctx.font = `500 12px ${sans()}`; ctx.fillStyle = t.text1; ctx.textBaseline = 'middle'; chart.$labelBoxes = [];
      const items = []; chart.data.datasets.forEach((set, d) => chart.getDatasetMeta(d).data.forEach((el, i) => items.push({el, p: set.data[i]})));
      const taken = items.map(({el, p}) => ({l: el.x - p.r, r: el.x + p.r, t: el.y - p.r, b: el.y + p.r, own: p.id}));
      // Bubble labels keep clear of the quadrant headings.
      taken.push(...(chart.$quadBoxes || []));
      // Median labels sit on a backing, at whichever end of the line no bubble covers.
      const mx = chart.scales.x.getPixelForValue(medianX), my = chart.scales.y.getPixelForValue(medianY);
      const tag = (text, spots) => {
        ctx.font = `600 11px ${mono()}`; const w = ctx.measureText(text).width + 12, h = 18;
        const boxAt = s => ({l: s.x, r: s.x + w, t: s.y, b: s.y + h, own: null});
        const s = spots.map(f => f(w, h)).find(c => !taken.some(o => c.x < o.r && c.x + w > o.l && c.y < o.b && c.y + h > o.t)) || spots[0](w, h);
        ctx.fillStyle = t.surface; ctx.strokeStyle = t.text3; ctx.lineWidth = 1; ctx.beginPath(); ctx.roundRect(s.x, s.y, w, h, 4); ctx.fill(); ctx.stroke();
        ctx.fillStyle = t.text1; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(text, s.x + 6, s.y + h / 2 + 0.5);
        taken.push(boxAt(s)); ctx.font = `500 12px ${sans()}`; ctx.fillStyle = t.text1;
      };
      tag(`median ${Math.round(medianY)}%`, [(w, h) => ({x: a.right - w - 6, y: my - h / 2}), (w, h) => ({x: a.left + 6, y: my - h / 2}), (w, h) => ({x: (a.left + mx) / 2 - w / 2, y: my - h / 2}), (w, h) => ({x: (mx + a.right) / 2 - w / 2, y: my - h / 2})]);
      tag(`median ${int(medianX)} reviews`, [(w, h) => ({x: mx - w / 2, y: a.bottom - h - 4}), (w, h) => ({x: mx - w / 2, y: a.top + 4})]);
      const hits = (box, id) => box.l < a.left || box.r > a.right || box.t < a.top || box.b > a.bottom || taken.some(o => o.own !== id && box.l < o.r && box.r > o.l && box.t < o.b && box.b > o.t);
      // Largest bubbles claim their label spot first.
      for (const {el, p} of [...items].sort((x, y) => y.p.r - x.p.r)) {
        const w = ctx.measureText(p.short).width, g = 6;
        const spots = [
          {x: el.x + p.r + g, y: el.y, align: 'left'}, {x: el.x - p.r - g, y: el.y, align: 'right'},
          {x: el.x, y: el.y - p.r - 11, align: 'center'}, {x: el.x, y: el.y + p.r + 11, align: 'center'},
          {x: el.x + p.r + g, y: el.y - 14, align: 'left'}, {x: el.x + p.r + g, y: el.y + 14, align: 'left'},
          {x: el.x - p.r - g, y: el.y - 14, align: 'right'}, {x: el.x - p.r - g, y: el.y + 14, align: 'right'},
          // Further out, for crowded clusters.
          {x: el.x, y: el.y - p.r - 27, align: 'center'}, {x: el.x, y: el.y + p.r + 27, align: 'center'},
          {x: el.x + p.r + g, y: el.y - 28, align: 'left'}, {x: el.x + p.r + g, y: el.y + 28, align: 'left'},
          {x: el.x - p.r - g, y: el.y - 28, align: 'right'}, {x: el.x - p.r - g, y: el.y + 28, align: 'right'},
          {x: el.x, y: el.y - p.r - 43, align: 'center'}, {x: el.x, y: el.y + p.r + 43, align: 'center'},
        ];
        const boxOf = s => { const l = s.align === 'left' ? s.x : s.align === 'right' ? s.x - w : s.x - w / 2; return {l, r: l + w, t: s.y - 8, b: s.y + 8}; };
        // If every spot is taken, use the one that overlaps least rather than the first.
        const overlap = box => taken.reduce((sum, o) => o.own === p.id ? sum : sum + Math.max(0, Math.min(box.r, o.r) - Math.max(box.l, o.l)) * Math.max(0, Math.min(box.b, o.b) - Math.max(box.t, o.t)), 0)
          + (box.l < a.left || box.r > a.right || box.t < a.top || box.b > a.bottom ? 1e6 : 0);
        const spot = spots.find(s => !hits(boxOf(s), p.id)) || [...spots].sort((s1, s2) => overlap(boxOf(s1)) - overlap(boxOf(s2)))[0];
        const placed = boxOf(spot); taken.push({...placed, own: null}); (chart.$labelBoxes ||= []).push({...placed, id: p.id}); ctx.textAlign = spot.align; ctx.fillText(p.short, spot.x, spot.y);
      }
      ctx.restore();
    }};
    const group = (type, color, label) => ({label, data: points.filter(p => p.type === type).map(p => ({x: p.x, y: p.y, r: radius(p), short: p.short, name: p.name, id: p.id})),
      backgroundColor: fade(color, 0.32), borderColor: color, borderWidth: 1.5, hoverBackgroundColor: fade(color, 0.55)});
    return {type: 'bubble', plugins: [decorate], data: {datasets: [group('fix', fix, 'Fix'), group('explore', explore, 'Explore')]},
      options: base(t, {interaction: {mode: 'nearest', intersect: true}, layout: {padding: {top: 6, right: 12}},
        onClick(event, items, chart) { if (items.length) onPick(chart.data.datasets[items[0].datasetIndex].data[items[0].index].id); },
        onHover(event, items) { event.native.target.style.cursor = items.length ? 'pointer' : 'default'; },
        scales: {x: {type: 'logarithmic', min: smallest / 1.35, max: biggest * 1.45, grid: {color: fade(t.border, 0.5)}, border: {display: false}, ticks: {...tick(t), callback: v => [5, 10, 20, 50, 100, 200, 500, 1000, 2000].includes(v) ? int(v) : ''}, title: {display: true, text: 'Reviews matched (log scale)', color: t.text3, font: {family: sans(), size: 11}}},
          y: {min: yMin, max: yMax, grid: {color: c => c.tick.value < 0 || c.tick.value > 100 ? 'transparent' : fade(t.border, 0.5)}, border: {display: false}, ticks: {...tick(t), stepSize: 10, callback: v => v < 0 || v > 100 || v % 10 ? '' : `${v}%`}, title: {display: true, text: 'Share at 1 to 2 stars', color: t.text3, font: {family: sans(), size: 11}}}},
        plugins: {legend: legend(t), tooltip: tooltip(t, {title: items => items[0].raw.name, label: c => ` ${int(c.raw.x)} reviews · ${Math.round(c.raw.y)}% at 1 to 2 stars`})}})};
  },
};

/* ---------- card ---------- */

function render(entry, animate = true) {
  entry.chart?.destroy();
  if (!window.Chart) { entry.message.hidden = false; return; }
  entry.message.hidden = true;
  const config = builders[entry.model.kind](entry.model.data);
  if (entry.anchors) linkRows(entry, config);
  if (!animate) config.options.animation = false;
  entry.chart = new window.Chart(entry.canvas, config);
}

// Row links for horizontal bar charts. Each row's label is covered by a real <a>, kept in place as the
// chart lays out, so it works with the keyboard and opens in a new tab like any link. A click on the bar
// itself follows the same link; the bars keep their tooltips.
function linkRows(entry, config) {
  const rowAt = (event, chart) => {
    const a = chart.chartArea; if (event.y < a.top || event.y > a.bottom) return -1;
    const index = Math.round(chart.scales.y.getValueForPixel(event.y));
    return index >= 0 && index < entry.anchors.length ? index : -1;
  };
  config.plugins = [...(config.plugins || []), {id: 'rowLinks', afterDraw(chart) {
    const a = chart.chartArea, band = (a.bottom - a.top) / entry.anchors.length;
    entry.anchors.forEach((anchor, index) => {
      const middle = chart.scales.y.getPixelForValue(index);
      anchor.style.top = `${middle - band / 2 + 1}px`; anchor.style.height = `${band - 2}px`; anchor.style.width = `${Math.max(0, a.left - 4)}px`;
    });
  }}];
  config.options.onClick = (event, items, chart) => { const index = rowAt(event, chart); if (index >= 0) entry.anchors[index].click(); };
  config.options.onHover = (event, items, chart) => { event.native.target.style.cursor = rowAt(event, chart) >= 0 ? 'pointer' : 'default'; };
}

// model: {title, subtitle, kind, data, height, table: {columns, rows}, legend: [{token, name, value, share}], span,
//   links: [{name, href, label}] one per row of a horizontal bar chart, in row order,
//   takeaways: [{text, href, onClick}] the Overview takeaways that rest on this chart, shown as back-links under it}
export function chartCard(model) {
  const card = node('section', undefined, `chart-card${model.span ? ` span-${model.span}` : ''}`);
  if (model.id) card.id = `chart-${model.id}`;
  const header = node('div', undefined, 'chart-header');
  const heading = node('div'); heading.append(node('h3', model.title), node('p', model.subtitle));
  const toggle = node('button', 'View as table', 'table-toggle'); toggle.type = 'button'; toggle.setAttribute('aria-pressed', 'false');
  header.append(heading, toggle);
  const body = node('div', undefined, model.legend ? `chart-body split${model.stack ? ' stacked' : ''}` : 'chart-body');
  const wrap = node('div', undefined, 'chart-wrap'); wrap.style.height = `${model.height || 280}px`;
  const canvas = node('canvas'); canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `${model.title}. Use View as table for the values.`); wrap.append(canvas); body.append(wrap);
  const anchors = (model.links || []).map(link => { const anchor = node('a', undefined, 'row-link'); anchor.href = link.href; anchor.dataset.deepLink = ''; anchor.title = link.label; anchor.setAttribute('aria-label', link.label); wrap.append(anchor); return anchor; });
  if (model.legend) {
    const list = node('ul', undefined, 'legend-list');
    for (const item of model.legend) { const row = node('li'); const dot = node('span', undefined, 'dot'); dot.style.background = `var(${item.token})`; const name = node('span', undefined, 'legend-name'); name.append(dot, node('span', item.name)); row.append(name, node('span', item.value, 'num'), node('span', item.share, 'num share')); list.append(row); }
    body.append(list);
  }
  const message = node('p', 'The chart library could not load. View as table to read the data.', 'note'); message.hidden = true;
  const tableWrap = node('div', undefined, 'table-wrap'); tableWrap.hidden = true;
  const table = node('table'); table.append(node('caption', model.title, 'sr-only'));
  const head = node('thead'), headRow = node('tr'); for (const column of model.table.columns) { const th = node('th', column); th.scope = 'col'; headRow.append(th); } head.append(headRow);
  const rows = node('tbody'); for (const values of model.table.rows) { const row = node('tr'); values.forEach((value, i) => { const cell = node('td', i || !model.links ? value : undefined, i ? 'num' : undefined); if (!i && model.links) { const link = model.links.find(l => l.name === value); if (link) { const anchor = node('a', value); anchor.href = link.href; anchor.dataset.deepLink = ''; cell.append(anchor); } else cell.textContent = value; } row.append(cell); }); rows.append(row); }
  table.append(head, rows); tableWrap.append(table);
  toggle.addEventListener('click', () => { const show = tableWrap.hidden; tableWrap.hidden = !show; body.hidden = show; message.hidden = show || !!window.Chart; toggle.textContent = show ? 'View as chart' : 'View as table'; toggle.setAttribute('aria-pressed', String(show)); });
  card.append(header, body, message, tableWrap);
  if (model.takeaways?.length) {
    const back = node('ul', undefined, 'chart-takeaways');
    for (const item of model.takeaways) { const row = node('li'), anchor = node('a', undefined, 'chart-takeaway'); anchor.href = item.href; anchor.append(node('span', item.text)); if (item.onClick) anchor.addEventListener('click', event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); item.onClick(); }); row.append(anchor); back.append(row); }
    card.append(back);
  }
  const entry = {canvas, model, message, anchors: anchors.length ? anchors : null}; active.add(entry);
  requestAnimationFrame(() => { if (canvas.isConnected) render(entry); });
  return card;
}
