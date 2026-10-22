import {chartCard, clearCharts, redrawCharts, colorForLabel, LABEL_ORDER} from './charts.js';
const $ = selector => document.querySelector(selector);
const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
const button = (text, action, className) => { const el = node('button', text, className); el.type = 'button'; el.dataset.focusId = text; el.addEventListener('click', action); return el; };
const scopes = ['all', 'android', 'ios'];
const platformName = scope => ({all: 'All', android: 'Android', ios: 'iOS'})[scope];
let summary, insights, ui, reviewPromise, renderEpoch;
const state = {tab: 'overview', platform: 'all', deepKind: 'labels', deepName: '', deepTopic: '', deepLabel: '', deepStars: '', deepSort: 'helpful', deepPage: null, reviewPage: null, filters: {}, drawer: null, jump: null, chart: null, takeaway: null};
const nf = (value, digits) => value === null || value === undefined ? 'n/a' : new Intl.NumberFormat('en-US', {maximumFractionDigits: digits ?? ui.zero, minimumFractionDigits: digits ?? ui.zero}).format(value);
const pct = value => value === null || value === undefined ? 'n/a' : `${nf(value)}%`;
const dateText = value => new Date(value).toLocaleDateString('en-US', {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'});
const current = () => summary[state.platform];
const sortedGroups = groups => Object.entries(groups).sort((a, b) => b.at(ui.one).count - a.at(ui.one).count || a.at(ui.zero).localeCompare(b.at(ui.zero)));
const countNote = n => `n=${nf(n)}`;
let languageNames;
try { languageNames = new Intl.DisplayNames(['en'], {type: 'language'}); } catch { /* Codes remain usable without DisplayNames. */ }
function languageName(code) {
  if (code === 'und') return 'Undetermined';
  if (code === 'Other') return code;
  try { return languageNames?.of(code) || code; } catch { return code; }
}
function checkReviewClamps() { requestAnimationFrame(() => document.querySelectorAll('.review-card').forEach(card => card.updateClamp?.())); }
function errorView(error) { return node('p', error.message, 'error'); }
async function fetchJSON(file) { try { const response = await fetch(file); if (!response.ok) throw new Error(); return await response.json(); } catch { throw new Error(`Could not load ${file}. Please refresh or check the local server.`); } }
async function reviews() {
  reviewPromise ||= fetchJSON('data/reviews.json').then(data => data.rows.map(values => {
    const row = Object.fromEntries(data.columns.map((key, index) => [key, values.at(index)]));
    row.search = [row.title, row.review_text, row.english_translation, row.topic].join(' ').toLocaleLowerCase();
    return row;
  }));
  return reviewPromise;
}
function hashState() {
  const [tab, query] = location.hash.slice(ui.one).split('?');
  const params = new URLSearchParams(query || '');
  const platform = params.get('platform');
  state.tab = ['overview', 'deep-dive', 'opportunities', 'reviews'].includes(tab) ? tab : 'overview';
  state.platform = scopes.includes(platform) ? platform : 'all';
  state.chart = state.tab === 'overview' ? params.get('chart') : null;
  state.takeaway = state.tab === 'overview' ? params.get('takeaway') : null;
  if (state.tab === 'deep-dive') {
    const previousKind = state.deepKind, previousName = state.deepName;
    state.deepKind = ['labels', 'categories'].includes(params.get('mode')) ? params.get('mode') : 'labels';
    const groups = sortedGroups(current()[state.deepKind]);
    const group = params.get('group');
    state.deepName = groups.some(([name]) => name === group) ? group : groups.at(ui.zero).at(ui.zero);
    if (previousKind !== state.deepKind || previousName !== state.deepName) resetDeepFilters();
  }
}
function navigate(tab = state.tab, platform = state.platform) {
  const params = new URLSearchParams({platform});
  if (tab === 'deep-dive') {
    const groups = sortedGroups(summary[platform][state.deepKind]);
    if (!groups.some(([name]) => name === state.deepName)) state.deepName = groups.at(ui.zero).at(ui.zero);
    params.set('mode', state.deepKind); params.set('group', state.deepName);
  }
  const next = `#${tab}?${params.toString().replaceAll('+', '%20')}`;
  if (location.hash === next) renderPage(); else location.hash = next;
}
function changePlatform(platform) { state.deepPage = state.reviewPage = ui.one; if (state.drawer) state.drawer.page = ui.one; navigate(state.tab, platform); }
function setNavigation() {
  for (const tab of document.querySelectorAll('[data-tab]')) {
    const selected = tab.dataset.tab === state.tab;
    tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? ui.tab_active : ui.tab_inactive;
  }
  $('#content').setAttribute('aria-labelledby', `tab-${state.tab}`);
  for (const toggle of document.querySelectorAll('#platforms [data-platform]')) {
    toggle.replaceChildren(node('span', platformName(toggle.dataset.platform)), node('span', nf(summary[toggle.dataset.platform].stats.count), 'num'));
    toggle.setAttribute('aria-pressed', String(toggle.dataset.platform === state.platform));
  }
}
const SVG_NS = 'http://www.w3.org/2000/svg';
const ICONS = {
  download: {d: ['M8 2.5v7.5m0 0L5 7m3 3l3-3M3 13h10']},
  theme: {d: ['M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z'], fills: ['M8 2a6 6 0 0 0 0 12z']},
  star: {fills: ['M8 1.7l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.5l-3.8 2 .7-4.3-3.1-3 4.3-.6z']},
  fix: {d: ['M10.4 2.6a3 3 0 0 0-3.8 3.8L2.6 10.4l3 3 4-4a3 3 0 0 0 3.8-3.8l-1.9 1.9-1.6-.5-.5-1.6z']},
  explore: {d: ['M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z', 'M10.6 5.4L9.2 9.2 5.4 10.6 6.8 6.8z']},
  arrow: {d: ['M3 8h10m0 0L9.5 4.5M13 8l-3.5 3.5']},
};
function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true'); svg.classList.add('icon');
  for (const d of ICONS[name].d || []) { const path = document.createElementNS(SVG_NS, 'path'); path.setAttribute('d', d); path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.5'); path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round'); svg.append(path); }
  for (const d of ICONS[name].fills || []) { const path = document.createElementNS(SVG_NS, 'path'); path.setAttribute('d', d); path.setAttribute('fill', 'currentColor'); svg.append(path); }
  return svg;
}
const dotted = (text, token, tag = 'span') => { const el = node(tag, undefined, 'with-dot'); const dot = node('span', undefined, 'dot'); dot.style.background = `var(${token})`; el.append(dot, node('span', text)); return el; };
function stat(name, value, note, token) {
  const el = node('div', undefined, 'stat');
  el.append(token ? dotted(name, token, 'p') : node('p', name), node('p', value, 'stat-value'), node('p', note, 'stat-note'));
  el.firstChild.classList.add('stat-name'); return el;
}
const sectionHeading = (title, note) => { const el = node('div', undefined, 'section-heading'); el.append(node('h2', title)); if (note) el.append(node('p', note)); return el; };
const categoryEntries = groups => sortedGroups(groups).map(([name, stats]) => ({name, ...stats}));
const isSmall = entry => (entry.category_count ?? entry.count) < ui.small_category;
const categoryLabel = entry => isSmall(entry) ? `${entry.name} (n<${nf(ui.small_category)})` : entry.name;
const share = (part, whole) => whole ? `${Math.round(part / whole * 100)}%` : 'n/a';
const rowsHeight = (count, row = 30, pad = 70) => Math.max(200, count * row + pad);
const short = (text, limit = 26) => { if (text.length <= limit) return text; const cut = text.slice(0, limit); return `${cut.slice(0, Math.max(cut.lastIndexOf(' '), 12))}…`; };
// A link to one category's page in Deep Dive, in the same form navigate() writes.
const categoryLink = name => ({name, href: `#deep-dive?${new URLSearchParams({platform: state.platform, mode: 'categories', group: name}).toString().replaceAll('+', '%20')}`, label: `Read the ${name} reviews in Deep Dive`});
// A link to one chart on the Overview page. The href reopens the page at that chart; a plain click scrolls there without a reload.
const chartHref = id => `#overview?${new URLSearchParams({platform: state.platform, chart: id})}`;
function jumpToChart(id) { const target = document.getElementById(`chart-${id}`); if (!target) return; target.classList.add('highlight'); setTimeout(() => target.classList.remove('highlight'), 2400); target.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); const heading = target.querySelector('h3'); heading.tabIndex = -1; heading.focus({preventScroll: true}); }
// A takeaway is a conclusion, the numbers behind it, and the next thing a PM would do about it.
// Every figure is computed from the current scope so the text stays right under the platform toggle.
// The wording is authored; the numbers, ranks, and conditional phrasing are not.
const takeawayHref = index => `#overview?${new URLSearchParams({platform: state.platform, takeaway: index})}`;
function jumpToTakeaway(index) { const target = document.getElementById(`takeaway-${index}`); if (!target) return; target.classList.add('highlight'); setTimeout(() => target.classList.remove('highlight'), 2400); target.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); const heading = target.querySelector('h3'); heading.tabIndex = -1; heading.focus({preventScroll: true}); }
const insightCount = id => { for (const group of ['improvements', 'feature_requests', 'strengths', 'callouts']) for (const item of insights[group]) if (item.id === id) return item.scopes[state.platform].stats.count; return ui.zero; };
const opportunityJump = (id, text) => ({text, onClick: () => { state.jump = id; navigate('opportunities'); }, href: `#opportunities?${new URLSearchParams({platform: state.platform})}`});
const deepJump = (mode, group, text, platform = state.platform) => ({text, href: `#deep-dive?${new URLSearchParams({platform, mode, group}).toString().replaceAll('+', '%20')}`});
function takeawayPoints(data, weeks, categories) {
  // Findings + findings = insight = hypothesis. Each card holds two or three findings from different cuts of the reviews
  // (helpful votes, co-occurrence, platform, time, competitors), the tension they add up to for the user and for the
  // company, and the idea that tension suggests, as a test. Every figure comes from summary.json for the current scope.
  const s = data.stats, F = data.facts || {}, r1 = value => nf(value, 1), r2 = value => nf(value, ui.rating_digits), points = [];
  const [praiseLabel, complaintLabel] = ['Specific Praise', 'Specific Complaint'];
  const cat = name => categories.find(c => c.name === name), complaints = c => c?.by_label[complaintLabel] ?? ui.zero, praise = c => c?.by_label[praiseLabel] ?? ui.zero;
  const scopeNote = state.platform === 'all' ? '' : `${platformName(state.platform)} `, ok = c => c && !isSmall(c), x = value => `${r1(value)}x`, REV = 'Reviews';
  const pair = (a, b) => (F.pairs || []).find(q => (q.a === a && q.b === b) || (q.a === b && q.b === a));
  const V = F.votes?.by, votesFor = name => V?.[name] ? x(V[name].ratio) : null, skew = name => F.skew?.by?.[name], five = name => F.five_star?.by?.[name], comp = name => F.competitors?.[name];
  const all = state.platform === 'all', ratePct = v => nf(Math.round(v));

  const monthName = m => new Date(`${m}-15T00:00:00Z`).toLocaleDateString('en-US', {month: 'short', year: 'numeric', timeZone: 'UTC'});
  const spikeFor = name => (F.spikes || []).find(q => q.category === name);
  const accuracy = cat('Transcription Accuracy'), prod = cat('Productivity & Time Saved');

  // 1. A cap on something that was unlimited is read as a loss.
  const limit = cat('Free Word Limit'), price = cat('Pricing & Value'), lp = pair('Free Word Limit', 'Pricing & Value'), sp = spikeFor('Free Word Limit');
  if (ok(limit) && sp) { const weekAvg = sp.week_avg_rating, priorAvg = sp.before_week_avg_rating;
    const priceSpike = (F.spikes || []).find(q => q.category === 'Pricing & Value' && q.week === sp.week), surprise = insightCount('i_limit_surprise'), v = sp.versions[ui.zero];
    points.push({chart: 'satisfaction', see: 'Satisfaction by category', title: 'A cap on something that was unlimited is read as a loss, not a price',
      findings: [{source: REV, text: `${nf(sp.count)} ${scopeNote}reviews about the free word limit in the week of ${dateText(sp.week)}, against ${r1(sp.before_mean)} a week before it${v ? `, mostly on ${platformName(v.platform)} ${v.version}` : ''}${priceSpike ? `. Price complaints went from ${r1(priceSpike.before_mean)} a week to ${nf(priceSpike.count)}` : ''}.${weekAvg && priorAvg ? ` Substantive reviews that week averaged ${r2(weekAvg)} stars against ${r2(priorAvg)} in the weeks before.` : ''}`},
        ...(lp ? [{source: REV, text: `${nf(lp.count)} reviews pair the limit with price, ${x(lp.lift)} what chance would give (${r2(lp.avg_rating)} stars)${surprise ? `; ${nf(surprise)} say it arrived without warning` : ''}.`}] : []),
        ...(ok(accuracy) ? [{source: REV, text: `Accuracy praise did not move: ${nf(praise(accuracy))} ${scopeNote}reviews praise transcription accuracy (${r2(accuracy.avg_rating)} stars), and many one-star limit reviews say the dictation still works.`}] : [])],
      insight: 'The product did not get worse; the deal did. A cap on something that was unlimited is read as a loss, and the heaviest free users, whose reviews recruited everyone else, became the loudest. Wispr wants revenue from exactly those users; those users want the thing they were given.',
      hypothesis: 'A meter and a warning before the cap, plus a grandfathered allowance for users who were heavy before it, keep more of the pre-cap cohort at 30 days than the hard stop, with no loss in upgrades. Test on the cohort active in the month before the cap.',
      more: opportunityJump('i_word_limit', 'See the word-limit opportunity')}); }

  // 2. Flow wins the transcription and loses the tap.
  const apple = comp('Apple Dictation'), bubble = cat('Floating Bubble & Overlay'), handoff = cat('Keyboard & App Switching'), skH = skew('Keyboard & App Switching');
  if (apple && (ok(bubble) || ok(handoff))) { const appleAcc = apple.over.find(o => o[0] === 'Transcription Accuracy'), sw = insightCount('i_switch'), gone = insightCount('i_bubble_gone'), bank = insightCount('i_banking');
    points.push({chart: 'competitors', see: 'Competitors named', title: 'Flow wins the transcription and loses the tap',
      findings: [{source: REV, text: `Apple Dictation is named in ${nf(apple.count)} ${scopeNote}reviews, ${nf(apple.praise)} praise against ${nf(apple.complaints)} complaints (${r2(apple.avg_rating)} stars)${appleAcc ? `, ${x(appleAcc[2])} over-represented in accuracy reviews` : ''}: people name the built-in dictation to say Flow hears better.`},
        ...(ok(handoff) ? [{source: REV, text: `${nf(complaints(handoff))} complaints are about the keyboard and hand-off (${r2(handoff.avg_rating)} stars)${skH && all ? `, ${ratePct(skH.ios_pct)}% from iPhone` : ''}${sw ? `; ${nf(sw)} describe being sent out of their app to dictate` : ''}.`}] : []),
        ...(ok(bubble) ? [{source: REV, text: `${nf(complaints(bubble))} complaints are about the Android bubble (${r2(bubble.avg_rating)} stars)${votesFor('Floating Bubble & Overlay') ? `, with ${votesFor('Floating Bubble & Overlay')} its share of helpful votes` : ''}${gone ? `; ${nf(gone)} say it disappears` : ''}${bank ? `, ${nf(bank)} say banking apps block it` : ''}.`}] : [])],
      insight: 'People judge dictation by the first tap, not the last word. The phone gives its own dictation the tap for free, on every keyboard, with no overlay to grant. Flow wins the transcription and loses the entry, and every step it adds before the first word spends the accuracy advantage it is named for.',
      hypothesis: 'Time from intent to first word, by platform, predicts weekly retention better than accuracy does. Cutting it on iPhone (dictate from the keyboard without leaving the app) and on Android (a bubble that survives) lifts retention more than the next accuracy gain.',
      more: opportunityJump(ok(handoff) ? 'i_switch' : 'i_bubble', ok(handoff) ? 'See the hand-off opportunity' : 'See the bubble opportunities')}); }

  // 3. The permission screen is the first review.
  const privacy = cat('Privacy & Security'), setup = cat('Setup & Permissions'), login = cat('Login & Account');
  if (ok(privacy) && ok(setup)) { const full = insightCount('i_privacy');
    points.push({chart: 'satisfaction', see: 'Satisfaction by category', title: 'The permission screen is the first review, and the OS writes it',
      findings: [{source: REV, text: `${nf(complaints(privacy))} ${scopeNote}complaints are about the access Flow asks for (${r2(privacy.avg_rating)} stars)${full ? `; ${nf(full)} name full keyboard or accessibility access as the worry` : ''}. Setup ${r2(setup.avg_rating)} stars${ok(login) ? `, login ${r2(login.avg_rating)}` : ''}: the lowest-rated areas on the page.`},
        ...(votesFor('Login & Account') && votesFor('Productivity & Time Saved') ? [{source: REV, text: `On Google Play, login complaints get ${votesFor('Login & Account')} their share of helpful votes; praise for time saved gets ${votesFor('Productivity & Time Saved')}.`}] : []),
        ...(ok(accuracy) && ok(prod) ? [{source: REV, text: `The people who get past the door rate accuracy ${r2(accuracy.avg_rating)} and time saved ${r2(prod.avg_rating)}.`}] : [])],
      insight: 'Flow needs full keyboard access and an accessibility service to work in every app, which is exactly what spyware asks for. The people who refuse never dictate a word, never see the accuracy everyone else praises, and leave the lowest ratings on the page.',
      hypothesis: 'A permission screen that answers the two questions reviewers ask (what the access is used for, and whether audio and text are stored) raises the grant rate and the first-dictation rate with no other change. Test on new installs, by platform.',
      more: opportunityJump(full ? 'i_privacy' : 'i_setup', 'See the setup and privacy opportunities')}); }

  // 4. Android's rating is a history of its launch.
  const endMonth = (summary.meta?.date_range?.end || '').slice(ui.zero, 7), M = (F.monthly || []).filter(m => m.month < endMonth && m.android && m.ios && m.android.n >= 50 && m.ios.n >= 50), launch = (F.spikes || []).filter(q => q.versions[ui.zero]?.platform === 'android' && q.versions[ui.zero]?.version.startsWith('1.0'));
  if (all && M.length >= 3 && summary.android?.stats?.count && summary.ios?.stats?.count) { const firstM = M[ui.zero], lastM = M.at(-ui.one);
    points.push({chart: 'about', see: 'What reviews are about', title: "Android's rating is a history of its launch, not of the app people install today",
      findings: [{source: REV, text: `Android averages ${r2(summary.android.stats.avg_rating)} stars against ${r2(summary.ios.stats.avg_rating)} on iPhone. By month, Android went from ${r2(firstM.android.avg_rating)} in ${monthName(firstM.month)} (${nf(firstM.android.n)} reviews) to ${r2(lastM.android.avg_rating)} in ${monthName(lastM.month)} (${nf(lastM.android.n)}); iPhone ${r2(firstM.ios.avg_rating)} to ${r2(lastM.ios.avg_rating)}.`},
        ...(launch.length ? [{source: REV, text: `In the week of ${dateText(launch[ui.zero].week)}, on Android ${launch[ui.zero].versions[ui.zero].version}, complaints about ${launch.map(q => `${q.category.toLowerCase()} (${nf(q.count)})`).join(', ')} all spiked at once: the launch week.`}] : [])],
      insight: 'Google Play shows the lifetime average, so every new Android user meets the launch week before they meet the product, while iPhone users meet a mature one. The gap between the platforms is mostly a gap in time.',
      hypothesis: 'Asking for a review after a successful dictation on current Android builds moves the visible average faster than any fix, because the current experience already rates near iPhone. Track the store average and a 30-day rolling average separately.',
      more: deepJump('categories', 'Reliability & Bugs', 'Read the reliability reviews', 'android')}); }

  // 5. The feature requests come from the happiest users.
  const FS = F.five_star, parity = cat('Desktop & Platform Parity');
  if (FS && FS.by['Desktop & Platform Parity'] && ok(parity)) { const top = Object.entries(FS.by).filter(([n]) => n !== 'Other').sort((a, b) => b[1].five_pct - a[1].five_pct).slice(ui.zero, 3), skP = skew('Productivity & Time Saved');
    points.push({chart: 'about', see: 'What reviews are about', title: 'The feature requests come from the happiest users',
      findings: [{source: REV, text: `${top.map(([n, v]) => `${ratePct(v.five_pct)}% of ${scopeNote}${n.toLowerCase()} complaints give five stars`).join(', ')}, against ${ratePct(FS.base_pct)}% of all complaints.`},
        {source: REV, text: `Desktop & Platform Parity holds ${nf(praise(parity))} praise and ${nf(complaints(parity))} complaints (${r2(parity.avg_rating)} stars); the asks are Chromebook, tablet and desktop.${skP && all ? ` Praise for time saved is ${ratePct(skP.ios_pct)}% iPhone against ${ratePct(F.skew.ios_base_pct)}% of all reviews.` : ''}`}],
      insight: 'The requests for desktop, tablet and editing features come from the happiest users, the ones already dictating on two devices. Those complaints predict expansion, not churn; the label calls them complaints, the star says they are a shopping list.',
      hypothesis: 'A second-device prompt shown to users who rate the mobile app 4+ in-app converts to a desktop or tablet install at a higher rate than any marketing channel. Measure second-device activation within 14 days.',
      more: opportunityJump('f_parity', 'See the parity requests')}); }

  // 6. "It fails" mostly means the chain before the model broke.
  const bugs = cat('Reliability & Bugs'), br = pair('Floating Bubble & Overlay', 'Reliability & Bugs'), bsu = pair('Reliability & Bugs', 'Setup & Permissions'), skB = skew('Reliability & Bugs');
  if (ok(bugs)) { const nothing = insightCount('i_nothing');
    points.push({chart: 'about', see: 'What reviews are about', title: '"It fails" mostly means the chain before the model broke',
      findings: [{source: REV, text: `${nf(complaints(bugs))} ${scopeNote}complaints are about dictation that fails, hangs or does not paste (${r2(bugs.avg_rating)} stars)${skB && all ? `, ${ratePct(100 - skB.ios_pct)}% of them on Android against ${ratePct(100 - F.skew.ios_base_pct)}% of all reviews` : ''}${nothing ? `; ${nf(nothing)} describe speaking and getting nothing back` : ''}.`},
        ...(br || bsu ? [{source: REV, text: `${br ? `${nf(br.count)} of them also name the bubble` : ''}${br && bsu ? ' and ' : ''}${bsu ? `${nf(bsu.count)} name setup or permissions (${x(bsu.lift)} what chance would give)` : ''}. The top reliability topics are the transcription failing and the bubble disappearing.`}] : []),
        ...(ok(accuracy) ? [{source: REV, text: `When it runs, it is praised: ${nf(praise(accuracy))} accuracy reviews at ${r2(accuracy.avg_rating)} stars.`}] : [])],
      insight: 'A failed dictation is usually the chain before the model breaking: an overlay the phone maker killed, an accessibility service that was revoked, a banking app that refused the bubble. The model is praised in the same reviews. Flow owns the model and not the chain, and the reviews blame it for both.',
      hypothesis: 'Dictation success measured from intent (bubble tap or keyboard mic) to text in the field, split by phone maker and Android version, will show failures concentrated in overlay and permission loss, not transcription. A health check that says why the bubble is gone, with a one-tap fix, raises success more than model work.',
      more: opportunityJump('i_fails', 'See the reliability opportunities')}); }

  // Fallback so every scope shows six: the star average against the text.
  const fiveStars = data.ratings.find(r => r.value === ui.rating_max), sc = data.labels[complaintLabel].count;
  if (points.length < 6 && fiveStars && s.substantive) points.push({chart: 'stars-sentiment', see: 'Stars vs sentiment', title: s.avg_rating > s.avg_sentiment ? 'The star average hides the problems' : 'The words run warmer than the stars',
    findings: [{source: REV, text: `${share(fiveStars.stars, s.count)} of ${scopeNote}reviews give ${ui.rating_max} stars, but only ${share(fiveStars.sentiment, s.sentiment_n)} read as a ${ui.rating_max} from the text. Average stars ${r2(s.avg_rating)}, average sentiment ${r2(s.avg_sentiment)}.`}],
    insight: `Stars measure the habit; the text measures the day. ${nf(sc)} of ${nf(s.substantive)} substantive reviews (${share(sc, s.substantive)}) are specific complaints the star average absorbs.`,
    hypothesis: 'Tracking specific complaints as a share of substantive reviews, beside the star average, shows product problems weeks before the rating moves.',
    more: deepJump('labels', complaintLabel, 'Read the specific complaints')});
  return points.slice(ui.zero, 6);
}
// The next step sits behind a disclosure so a card reads as one line of evidence until the reader asks for more.
function nextStep(text, more, label = 'Next step') {
  const details = node('details', undefined, 'next-step'), summary = node('summary'); summary.append(icon('arrow'), node('span', label)); details.append(summary, node('p', text));
  if (more) { const link = node('a', undefined, 'key-point-link secondary'); link.href = more.href; link.append(node('span', more.text), icon('arrow')); if (more.onClick) link.addEventListener('click', event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); more.onClick(); }); details.append(link); }
  return details;
}
// One card: findings (each tagged with its source), the insight they add up to, and the hypothesis to test.
function insightCard(point, index, idPrefix) {
  const n = index + ui.one, item = node('li', undefined, 'key-point'); item.id = `${idPrefix}-${n}`;
  item.append(node('p', String(n).padStart(ui.two, '0'), 'key-point-index'), node('h3', point.title), node('p', 'Findings', 'kp-label'));
  const findings = node('ol', undefined, 'findings');
  for (const f of point.findings.filter(f => f.text)) { const li = node('li'); li.append(node('span', f.source, 'src-tag'), node('span', f.text)); findings.append(li); }
  item.append(findings, node('p', 'Insight', 'kp-label'), node('p', point.insight, 'key-point-evidence'), nextStep(point.hypothesis, point.more, 'Hypothesis to test'));
  return item;
}
function takeaways(points) {
  const list = node('ol', undefined, 'key-points');
  points.forEach((point, index) => {
    const item = insightCard(point, index, 'takeaway'), link = node('a', undefined, 'key-point-link');
    link.href = chartHref(point.chart); link.append(node('span', `See chart: ${point.see}`), icon('arrow'));
    link.addEventListener('click', event => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); jumpToChart(point.chart); });
    item.append(link); list.append(item);
  });
  return list;
}
// Back-links from a chart to the takeaways that rest on it, in chartCard's {text, href, onClick} form.
const takeawayLinks = (points, chart) => points.map((point, index) => ({point, n: index + ui.one})).filter(({point}) => point.chart === chart).map(({point, n}) => ({text: `Takeaway ${String(n).padStart(ui.two, '0')}: ${point.title}`, href: takeawayHref(n), onClick: () => jumpToTakeaway(n)}));
function overview() {
  const root = node('div'); const data = current(), s = data.stats, L = data.labels;
  const band = node('div', undefined, 'stat-band');
  band.append(stat('Total reviews', nf(s.count), 'public store reviews'),
    stat('Average stars', nf(s.avg_rating, ui.rating_digits), `out of ${ui.rating_max} · ${countNote(s.count)}`, '--stars'),
    stat('Average sentiment', nf(s.avg_sentiment, ui.rating_digits), `LLM-scored · ${countNote(s.sentiment_n)} · leaves out ${nf(s.nonsense_count)} Nonsense`, '--sentiment'),
    stat('Substantive', pct(s.pct_substantive), `${nf(s.substantive)} name a feature, problem, or use`, '--praise'),
    stat('Rating mismatch', pct(s.pct_mismatch), `${nf(s.mismatch_count)} where stars and text differ by ${ui.mismatch_gap}+`, '--complaint'),
    stat('Not in English', pct(s.pct_non_english), `${nf(s.non_english)} translated for reading`));
  root.append(band);

  const lead = node('div', undefined, 'grid');
  const gg = L['Generic Good'].count, gb = L['Generic Bad'].count, ns = L['Nonsense'].count, sub = s.substantive;
  const sp = L['Specific Praise'].count, sc = L['Specific Complaint'].count, fr = L['Feature Request'].count;
  const steps = [
    {name: 'All reviews', start: 0, end: s.count, token: '--volume', strength: 0.45, value: s.count, link: s.count},
    {name: 'Generic praise', start: s.count - gg, end: s.count, token: '--good', strength: 0.6, value: gg, sign: '−', link: s.count - gg},
    {name: 'Generic complaints', start: s.count - gg - gb, end: s.count - gg, token: '--bad', strength: 0.6, value: gb, sign: '−', link: s.count - gg - gb},
    {name: 'Off-topic', start: s.count - gg - gb - ns, end: s.count - gg - gb, token: '--nonsense', strength: 0.6, value: ns, sign: '−', link: s.count - gg - gb - ns},
    {name: 'Substantive', start: 0, end: sub, token: '--volume', strength: 0.9, value: sub},
    {name: 'Praise', start: 0, end: sp, token: '--praise', strength: 1, value: sp},
    {name: 'Complaints', start: 0, end: sc, token: '--complaint', strength: 1, value: sc},
    {name: 'Requests', start: 0, end: fr, token: '--request', strength: 1, value: fr},
  ];
  lead.append(chartCard({id: 'signal', span: 12, kind: 'waterfall', height: 360, title: 'Where the signal is',
    subtitle: `By first label · ${share(sub, s.count)} of reviews say something specific, and everything below rests on them`,
    data: {steps}, table: {columns: ['Step', 'Reviews', 'Share of all'], rows: steps.map(st => [st.name, `${st.sign || ''}${nf(st.value)}`, share(st.value, s.count)])}}));
  root.append(lead);

  const weeks = data.weekly, points = takeawayPoints(data, weeks, categoryEntries(data.categories)), backlinks = chart => takeawayLinks(points, chart);
  root.append(sectionHeading('Insights', `${platformName(state.platform)} · findings + findings = insight = hypothesis · each card adds up two or three findings from different cuts of the reviews into the tension behind them, then the idea to test · store reviews are self-selected, so these are hypotheses, not validated problems`), takeaways(points));

  const weekLabels = weeks.map(w => new Date(w.week).toLocaleDateString('en-US', {month: 'short', day: 'numeric', timeZone: 'UTC'}));
  const trend = node('div', undefined, 'grid'), thin = w => w.volume < ui.small_category;
  trend.append(chartCard({id: 'weekly', span: 12, kind: 'combo', height: 340, title: 'Volume and rating by week', takeaways: backlinks('weekly'),
    subtitle: `Bars count reviews on the left axis; lines show average stars and sentiment on the right, fixed at 1 to 5 · averages are left blank for weeks with fewer than ${nf(ui.small_category)} reviews · complete weeks, Monday start · ${countNote(s.weekly_n)}`,
    data: {labels: weekLabels, volume: weeks.map(w => w.volume), stars: weeks.map(w => thin(w) ? null : w.avg_rating), sentiment: weeks.map(w => thin(w) ? null : w.avg_sentiment)},
    table: {columns: ['Week of', 'Reviews', 'Average stars', 'Average sentiment'], rows: weeks.map((w, i) => [weekLabels[i], nf(w.volume), thin(w) ? '–' : nf(w.avg_rating, ui.rating_digits), thin(w) ? '–' : nf(w.avg_sentiment, ui.rating_digits)])}}));
  root.append(sectionHeading('How reviews trend'), trend);

  const mood = node('div', undefined, 'grid');
  const labelSegments = LABEL_ORDER.map(name => ({name, value: L[name].count, token: colorForLabel(name)}));
  mood.append(chartCard({span: 4, kind: 'donut', stack: true, height: 190, title: 'What kind of review', subtitle: `First label per review · ${countNote(s.count)}`,
    data: {segments: labelSegments, center: nf(s.count), caption: 'reviews'},
    legend: labelSegments.map(seg => ({token: seg.token, name: seg.name, value: nf(seg.value), share: share(seg.value, s.count)})),
    table: {columns: ['Label', 'Reviews', 'Share'], rows: labelSegments.map(seg => [seg.name, nf(seg.value), share(seg.value, s.count)])}}));
  const sent = v => data.ratings.filter(r => v.includes(r.value)).reduce((sum, r) => sum + r.sentiment, 0);
  const moodSegments = [{name: 'Positive, 4 to 5', value: sent([4, 5]), token: '--praise'}, {name: 'Neutral, 3', value: sent([3]), token: '--neutral'}, {name: 'Negative, 1 to 2', value: sent([1, 2]), token: '--complaint'}];
  mood.append(chartCard({span: 4, kind: 'donut', stack: true, height: 190, title: 'How the text reads', subtitle: `LLM sentiment of the words alone · ${countNote(s.sentiment_n)} · Nonsense left out`,
    data: {segments: moodSegments, center: share(moodSegments[0].value, s.sentiment_n), caption: 'positive'},
    legend: moodSegments.map(seg => ({token: seg.token, name: seg.name, value: nf(seg.value), share: share(seg.value, s.sentiment_n)})),
    table: {columns: ['Sentiment', 'Reviews', 'Share'], rows: moodSegments.map(seg => [seg.name, nf(seg.value), share(seg.value, s.sentiment_n)])}}));
  mood.append(chartCard({id: 'stars-sentiment', span: 4, kind: 'groupedBars', height: 360, title: 'Stars vs sentiment', takeaways: backlinks('stars-sentiment'), subtitle: 'Reviews at each score. Stars pile up at 5; the words are more measured',
    data: {labels: data.ratings.map(r => String(r.value)), series: [{name: 'Stars given', token: '--stars', values: data.ratings.map(r => r.stars)}, {name: 'Sentiment of text', token: '--sentiment', values: data.ratings.map(r => r.sentiment)}]},
    table: {columns: ['Score', 'Stars given', 'Sentiment of text'], rows: data.ratings.map(r => [String(r.value), nf(r.stars), nf(r.sentiment)])}}));
  root.append(sectionHeading('The mood'), mood);

  const categories = categoryEntries(data.categories);
  const satisfaction = [...categories].filter(c => c.avg_rating !== null).sort((a, b) => b.avg_rating - a.avg_rating);
  const [praiseLabel, complaintLabel, requestLabel] = ['Specific Praise', 'Specific Complaint', 'Feature Request'];
  const topics = node('div', undefined, 'grid');
  topics.append(chartCard({id: 'about', span: 7, kind: 'stackedBars', height: rowsHeight(categories.length), title: 'What reviews are about', takeaways: backlinks('about'),
    subtitle: `Reviews per category, split by their first label · a review with two categories counts in both · ${countNote(s.substantive)} substantive · select a category to read its reviews`,
    links: categories.map(c => categoryLink(c.name)),
    data: {linked: true, labels: categories.map(categoryLabel), faded: categories.map(isSmall), series: [
      {name: 'Praise', token: '--praise', values: categories.map(c => c.by_label[praiseLabel])},
      {name: 'Requests', token: '--request', values: categories.map(c => c.by_label[requestLabel])},
      {name: 'Complaints', token: '--complaint', values: categories.map(c => c.by_label[complaintLabel])}]},
    table: {columns: ['Category', 'Praise', 'Requests', 'Complaints', 'Total'], rows: categories.map(c => [c.name, nf(c.by_label[praiseLabel]), nf(c.by_label[requestLabel]), nf(c.by_label[complaintLabel]), nf(c.count)])}}));
  topics.append(chartCard({id: 'satisfaction', span: 5, kind: 'diverging', height: rowsHeight(satisfaction.length), title: 'Satisfaction by category', takeaways: backlinks('satisfaction'),
    subtitle: `Mean stars, drawn from the midpoint of ${ui.weekly_rating_min}.0 · right is above, left is below · select a category to read its reviews`,
    links: satisfaction.map(c => categoryLink(c.name)),
    data: {linked: true, labels: satisfaction.map(categoryLabel), values: satisfaction.map(c => c.avg_rating), center: ui.weekly_rating_min, faded: satisfaction.map(isSmall), notes: satisfaction.map(c => countNote(c.count))},
    table: {columns: ['Category', 'Mean stars', 'Reviews'], rows: satisfaction.map(c => [c.name, nf(c.avg_rating, ui.rating_digits), nf(c.count)])}}));
  root.append(sectionHeading('What people talk about', `${platformName(state.platform)} · ${countNote(s.substantive)} substantive reviews`), topics);

  const platforms = scopes.filter(p => p !== 'all');
  const compare = node('div', undefined, 'grid');
  compare.append(chartCard({id: 'platform-mix', span: 6, kind: 'stackedBars', height: 210, title: 'Label mix by platform', takeaways: backlinks('platform-mix'), subtitle: 'Share of each first label · always shows both platforms',
    data: {percent: true, labels: platforms.map(p => `${platformName(p)} (${countNote(summary[p].stats.count)})`), series: LABEL_ORDER.map(name => ({name, token: colorForLabel(name), values: platforms.map(p => summary[p].labels[name].pct_of_scope)}))},
    table: {columns: ['Label', ...platforms.map(platformName)], rows: LABEL_ORDER.map(name => [name, ...platforms.map(p => `${nf(summary[p].labels[name].pct_of_scope, 1)}% (${nf(summary[p].labels[name].count)})`)])}}));
  const mismatch = node('section', undefined, 'chart-card span-6'); const mismatchHead = node('div', undefined, 'chart-header'), mismatchTitle = node('div');
  mismatchTitle.append(node('h3', 'Where stars and words disagree'), node('p', `Share of each label where stars and sentiment differ by ${ui.mismatch_gap} or more`)); mismatchHead.append(mismatchTitle); mismatch.append(mismatchHead);
  const table = node('table', undefined, 'meter-table'), body = node('tbody');
  for (const name of LABEL_ORDER) { const l = L[name], row = node('tr'), meterCell = node('td'), track = node('span', undefined, 'meter'), fill = node('span', undefined, 'meter-fill'); fill.style.width = `${l.pct_mismatch ?? 0}%`; track.append(fill); meterCell.append(track);
    const nameCell = node('td'); nameCell.append(dotted(name, colorForLabel(name))); row.append(nameCell, meterCell, node('td', pct(l.pct_mismatch), 'num'), node('td', `${nf(l.mismatch_count)} / ${nf(l.count)}`, 'num muted')); body.append(row); }
  table.append(body); mismatch.append(table); compare.append(mismatch);
  root.append(sectionHeading('Platforms and honesty of the stars'), compare);

  const over = node('div', undefined, 'grid');
  const showVersions = state.platform !== 'ios' && data.versions.length > 1;
  if (showVersions) { const most = Math.max(...data.versions.map(v => v.count)), versionMin = Math.max(ui.one, Math.floor(Math.min(...data.versions.map(v => v.avg_rating)) * ui.two) / ui.two);
    over.append(chartCard({id: 'versions', span: 6, kind: 'line', height: 280, title: 'Stars by Android version', takeaways: backlinks('versions'), subtitle: `Versions with ${nf(ui.hundred)} or more reviews, in release order · y-axis starts at ${nf(versionMin, ui.one)} · larger points have more reviews`,
      data: {labels: data.versions.map(v => v.name), values: data.versions.map(v => v.avg_rating), token: '--stars', min: versionMin, max: 5, digits: 1, name: 'Mean stars', radii: data.versions.map(v => 3 + 5 * Math.sqrt(v.count / most)), notes: data.versions.map(v => countNote(v.count))},
      table: {columns: ['Version', 'Mean stars', 'Reviews'], rows: data.versions.map(v => [v.name, nf(v.avg_rating, ui.rating_digits), nf(v.count)])}})); }
  over.append(chartCard({span: showVersions ? 6 : 12, kind: 'line', height: 280, title: '"It got worse" per week', subtitle: `Reviews that say the product declined · complete weeks · ${countNote(weeks.reduce((sum, w) => sum + w.regression, 0))}`,
    data: {labels: weekLabels, values: weeks.map(w => w.regression), token: '--complaint', fill: true, name: 'Reviews'},
    table: {columns: ['Week of', 'Reviews'], rows: weeks.map((w, i) => [weekLabels[i], nf(w.regression)])}}));
  root.append(sectionHeading('Over releases and time'), over);

  const competitors = [...data.competitors].filter(c => c.count).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const band3 = c => [c.star_counts[0] + c.star_counts[1], c.star_counts[2], c.star_counts[3] + c.star_counts[4]];
  const context = node('div', undefined, 'grid');
  context.append(chartCard({id: 'competitors', span: 7, kind: 'stackedBars', height: rowsHeight(competitors.length, 30, 80), title: 'Competitors named', takeaways: backlinks('competitors'),
    subtitle: `Reviews that name another product, split by the stars the reviewer gave ${summary.meta.product.name}`,
    data: {labels: competitors.map(c => c.name), series: [{name: '4 to 5 stars', token: '--praise', values: competitors.map(c => band3(c)[2])}, {name: '3 stars', token: '--neutral', values: competitors.map(c => band3(c)[1])}, {name: '1 to 2 stars', token: '--complaint', values: competitors.map(c => band3(c)[0])}]},
    table: {columns: ['Competitor', '4 to 5 stars', '3 stars', '1 to 2 stars', 'Total'], rows: competitors.map(c => [c.name, nf(band3(c)[2]), nf(band3(c)[1]), nf(band3(c)[0]), nf(c.count)])}}));
  const named = data.languages.filter(l => l.name !== 'Other'), top = named.slice(0, 6), rest = s.count - top.reduce((sum, l) => sum + l.count, 0);
  const languageSegments = [...top.map((l, i) => ({name: languageName(l.name), value: l.count, token: `--seq-${i + 1}`})), {name: 'Other languages', value: rest, token: '--neutral'}];
  context.append(chartCard({span: 5, kind: 'donut', height: 210, title: 'Languages', subtitle: `Language of the review text · ${countNote(s.count)}`,
    data: {segments: languageSegments, center: share(s.non_english, s.count), caption: 'not English'},
    legend: languageSegments.map(seg => ({token: seg.token, name: seg.name, value: nf(seg.value), share: share(seg.value, s.count)})),
    table: {columns: ['Language', 'Reviews', 'Share'], rows: languageSegments.map(seg => [seg.name, nf(seg.value), share(seg.value, s.count)])}}));
  root.append(sectionHeading('Context'), context);
  return root;
}
function field(name, control, className) { const el = node('label', undefined, `field ${className || ''}`); control.dataset.focusId = `field:${name}`; el.append(node('span', name), control); return el; }
function rememberFocus(container) { return container.contains(document.activeElement) ? document.activeElement.dataset.focusId : null; }
function restoreFocus(container, key) {
  if (!key || document.activeElement !== document.body) return;
  const target = container.querySelector(`[data-focus-id="${CSS.escape(key)}"]`);
  if (target && !target.disabled) target.focus();
  else container.querySelector('.pager button:not(:disabled)')?.focus();
}
function selectControl(options, value, action) { const select = node('select'); for (const [v, text] of options) { const option = node('option', text); option.value = v; select.append(option); } select.value = value; select.addEventListener('change', () => action(select.value)); return select; }
const starOptions = () => [['', 'All stars'], ...ui.rating_values.map(v => [String(v), v === ui.one ? `${v} star` : `${v} stars`])];
const sortOptions = () => [['helpful', 'Most helpful'], ['newest', 'Newest'], ['longest', 'Longest']];
function sortReviews(rows, sort) { return [...rows].sort((a, b) => (sort === 'helpful' ? b.thumbs_up - a.thumbs_up : sort === 'longest' ? b.review_text.length - a.review_text.length : ui.zero) || b.timestamp.localeCompare(a.timestamp) || a.review_id.localeCompare(b.review_id)); }
function reviewCard(row) {
  const card = node('article', undefined, 'review-card'); card.dataset.reviewId = row.review_id;
  const meta = node('div', undefined, 'review-meta'); const starBadge = node('span', undefined, `stars band-${row.rating <= ui.two ? 'low' : row.rating >= ui.rating_max - ui.one ? 'high' : 'mid'}`); starBadge.append(icon('star'), node('span', String(row.rating))); starBadge.setAttribute('aria-label', `${row.rating} stars`); meta.append(starBadge, node('span', platformName(row.platform), 'badge'), node('span', dateText(row.date_utc)), node('span', languageName(row.language), 'review-language'));
  if (row.app_version) meta.append(node('span', `v${row.app_version}`)); if (row.thumbs_up > ui.zero) meta.append(node('span', `${nf(row.thumbs_up)} helpful`)); card.append(meta);
  const chips = node('div', undefined, 'chips');
  for (const label of row.labels) { const chip = node('span', undefined, 'chip'), dot = node('span', undefined, 'dot'); dot.style.background = `var(${colorForLabel(label)})`; chip.append(dot, node('span', label)); chips.append(chip); }
  for (const category of row.categories) chips.append(node('span', category, 'chip')); card.append(chips);
  const content = node('div', undefined, 'review-content'); card.append(content);
  const showContent = () => {
  if (row.platform === 'ios' && row.title) content.append(node('h3', row.title, 'review-title'));
  const translated = row.language !== 'en' && row.language !== 'und' && row.english_translation;
  const text = node('p', translated ? row.english_translation : row.review_text, 'review-text clamped'); content.append(text);
  const actions = node('div', undefined, 'review-actions');
  const more = button('More', () => { const collapsed = text.classList.toggle('clamped'); more.textContent = collapsed ? 'More' : 'Less'; checkReviewClamps(); }); more.hidden = true;
  card.updateClamp = () => { if (text.getClientRects().length) more.hidden = text.classList.contains('clamped') && text.scrollHeight <= text.clientHeight; };
  const updateMore = checkReviewClamps;
  if (translated) { let original = false; const toggle = button('Show original', () => { original = !original; text.textContent = original ? row.review_text : row.english_translation; toggle.textContent = original ? 'Show translation' : 'Show original'; toggle.setAttribute('aria-pressed', String(original)); updateMore(); }); toggle.setAttribute('aria-pressed', 'false'); actions.append(toggle); }
  actions.append(more); content.append(actions); updateMore();
  if (row.topic) content.append(node('p', `Topic: ${row.topic}`, 'note'));
  };
  if (row.labels.includes('Nonsense')) {
    const notice = node('p', 'Off-topic review hidden', 'note');
    const show = button('Show', () => { content.replaceChildren(); showContent(); });
    content.append(notice, show);
  } else showContent();
  const flags = node('div', undefined, 'flags'); if (row.rating_mismatch) flags.append(node('span', 'Stars and text disagree')); if (row.regression_claim) flags.append(node('span', 'Says it got worse')); if (row.is_truncated) flags.append(node('span', 'Truncated by Play')); if (flags.childNodes.length) card.append(flags);
  return card;
}
function reviewList(rows, page, pageSize, onPage, clear) {
  const root = node('div'), count = rows.length; const pages = Math.max(ui.one, Math.ceil(count / pageSize)); page = Math.min(page, pages);
  if (!count) { const empty = node('div', undefined, 'empty'); empty.append(node('p', 'No reviews match'), button('Clear filters', clear)); root.append(empty); return root; }
  const list = node('div', undefined, 'review-list'); const offset = (page - ui.one) * pageSize; for (const row of rows.slice(offset, offset + pageSize)) list.append(reviewCard(row));
  const pager = node('div', undefined, 'pager'), buttons = node('div', undefined, 'buttons'); const previous = button('Previous', () => onPage(page - ui.one)), next = button('Next', () => onPage(page + ui.one)); previous.disabled = page === ui.one; next.disabled = page === pages; buttons.append(previous, next); pager.append(node('p', `${nf(offset + ui.one)}–${nf(Math.min(count, offset + pageSize))} of ${nf(count)} · page ${nf(page)} / ${nf(pages)}`), buttons); root.append(list, pager); return root;
}
function segmentBar(parts, className) { const bar = node('div', undefined, `segment-bar ${className || ''}`); const total = parts.reduce((sum, p) => sum + p.value, ui.zero); for (const p of parts) { if (!p.value) continue; const seg = node('span'); seg.style.flexGrow = String(p.value); seg.style.background = `var(${p.token})`; seg.title = `${p.name}: ${nf(p.value)} (${share(p.value, total)})`; bar.append(seg); } bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', parts.map(p => `${p.name} ${nf(p.value)}`).join(', ')); return bar; }
function compositionBar(stats, className) { const parts = [{name: 'Praise', value: stats.by_label['Specific Praise'], token: '--praise'}, {name: 'Requests', value: stats.by_label['Feature Request'], token: '--request'}, {name: 'Complaints', value: stats.by_label['Specific Complaint'], token: '--complaint'}]; if (className) return segmentBar(parts, className); const wrap = node('div', undefined, 'composition'); wrap.append(segmentBar(parts)); const key = node('p', undefined, 'composition-key'); for (const p of parts) key.append(dotted(`${p.name} ${nf(p.value)}`, p.token)); wrap.append(key); return wrap; }
function starBar(stats) { const tokens = ['--ramp-1', '--ramp-2', '--ramp-3', '--ramp-4', '--ramp-5']; const parts = stats.star_counts.map((value, i) => ({name: `${i + ui.one} star${i ? 's' : ''}`, value, token: tokens[i]})); const wrap = node('div', undefined, 'composition'); wrap.append(segmentBar(parts)); const key = node('p', undefined, 'composition-key'); for (const p of parts) key.append(dotted(`${p.name} ${nf(p.value)}`, p.token)); wrap.append(key); return wrap; }
function resetDeepFilters() { state.deepTopic = state.deepLabel = state.deepStars = ''; state.deepSort = 'helpful'; state.deepPage = ui.one; }
async function deepDive() {
  const rows = await reviews(), root = node('div', undefined, 'deep-layout'), data = current();
  const sidebar = node('aside', undefined, 'sidebar'); sidebar.setAttribute('aria-label', 'Deep Dive groups'); const switcher = node('div', undefined, 'segmented');
  for (const [kind, title] of [['labels', 'Labels'], ['categories', 'Categories']]) { const control = button(title, () => { state.deepKind = kind; state.deepName = sortedGroups(data[kind]).at(ui.zero).at(ui.zero); resetDeepFilters(); navigate(); }); control.setAttribute('aria-pressed', String(state.deepKind === kind)); switcher.append(control); } sidebar.append(switcher);
  const groups = sortedGroups(data[state.deepKind]); if (!groups.some(([name]) => name === state.deepName)) state.deepName = groups.at(ui.zero).at(ui.zero);
  const choose = name => { state.deepName = name; resetDeepFilters(); navigate(); };
  const dropdown = selectControl(groups.map(([name, stats]) => [name, `${name} · ${nf(stats.count)}`]), state.deepName, choose); sidebar.append(field('Choose a group', dropdown, 'sidebar-select'));
  const list = node('div', undefined, 'sidebar-list');
  for (const [name, stats] of groups) { const control = button('', () => choose(name)); control.dataset.focusId = `group:${name}`; const dot = node('span', undefined, 'dot'); dot.style.background = state.deepKind === 'labels' ? `var(${colorForLabel(name)})` : 'var(--text-4)'; const title = node('span', undefined, 'name-with-dot'); title.append(dot, node('span', name)); control.append(title, node('span', nf(stats.count), 'num')); if (state.deepKind === 'categories') control.append(compositionBar(stats, 'mini')); control.setAttribute('aria-pressed', String(name === state.deepName)); list.append(control); } sidebar.append(list); root.append(sidebar);
  const pane = node('div'), header = node('section', undefined, 'card detail-header'), stats = data[state.deepKind][state.deepName]; header.append(node('h2', state.deepName)); header.append(state.deepKind === 'categories' ? compositionBar(stats) : starBar(stats));
  const values = node('div', undefined, 'detail-stats'); values.append(node('span', `${nf(stats.count)} reviews`), node('span', `Stars ${nf(stats.avg_rating, ui.rating_digits)} · ${countNote(stats.count)}`), node('span', `Sentiment ${nf(stats.avg_sentiment, ui.rating_digits)} · ${countNote(stats.sentiment_n)}`), node('span', `${pct(stats.pct_low_star)} at low stars · ${nf(stats.low_star_count)} / ${nf(stats.count)}`), node('span', `${pct(stats.pct_mismatch)} mismatch · ${nf(stats.mismatch_count)} / ${nf(stats.count)}`)); header.append(values);
  if (state.deepKind === 'labels') { const takeaways = node('ul', undefined, 'takeaways'); for (const text of insights.label_takeaways[state.deepName] || []) takeaways.append(node('li', text)); header.append(takeaways); }
  else {
    header.append(node('p', insights.category_notes[state.deepName] || '', 'muted')); const byLabel = node('div', undefined, 'chips');
    const all = button('All labels', () => { state.deepLabel = ''; state.deepPage = ui.one; renderPage(); }, 'chip'); all.setAttribute('aria-pressed', String(!state.deepLabel)); byLabel.append(all);
    for (const label of summary.meta.taxonomy.specific_labels) { const control = button(`${label} · ${nf(stats.by_label[label])}`, () => { state.deepLabel = state.deepLabel === label ? '' : label; state.deepPage = ui.one; renderPage(); }, 'chip'); control.setAttribute('aria-pressed', String(state.deepLabel === label)); byLabel.append(control); } header.append(byLabel);
    const related = node('div', undefined, 'related'); related.append(node('h3', 'Related opportunities')); const chips = node('div', undefined, 'chips');
    for (const group of ['improvements', 'feature_requests', 'strengths']) for (const item of insights[group]) if ([...(item.match.categories_any || []), ...(item.match.categories_all || [])].includes(state.deepName) && item.scopes[state.platform].stats.count) { chips.append(button(item.scopes[state.platform].title, () => { state.jump = item.id; navigate('opportunities'); }, 'chip')); }
    if (chips.childNodes.length) related.append(chips); else related.append(node('p', 'No related opportunity in this scope.', 'note')); header.append(related);
  }
  pane.append(header);
  const topics = node('div', undefined, 'topics'); topics.append(node('h3', 'Top topics')); const chips = node('div', undefined, 'chips');
  for (const topic of stats.topics.filter(topic => topic.count >= ui.topic_min_count)) { const chip = button(`${topic.topic} · ${nf(topic.count)}`, () => { state.deepTopic = state.deepTopic === topic.topic ? '' : topic.topic; state.deepPage = ui.one; renderPage(); }, 'chip'); chip.setAttribute('aria-pressed', String(state.deepTopic === topic.topic)); chips.append(chip); } if (chips.childNodes.length) { topics.append(chips); pane.append(topics); }
  const toolbar = node('div', undefined, 'review-toolbar'); const set = (key, value) => { state[key] = value; state.deepPage = ui.one; renderPage(); };
  toolbar.append(field('Stars', selectControl(starOptions(), state.deepStars, v => set('deepStars', v))), field('Sort', selectControl(sortOptions(), state.deepSort, v => set('deepSort', v))), button('Clear filters', () => { resetDeepFilters(); renderPage(); })); pane.append(toolbar);
  const matched = sortReviews(rows.filter(r => (state.platform === 'all' || r.platform === state.platform) && (state.deepKind === 'labels' ? r.labels.at(ui.zero) === state.deepName : r.categories.includes(state.deepName)) && (!state.deepLabel || r.labels.at(ui.zero) === state.deepLabel) && (!state.deepTopic || r.topic === state.deepTopic) && (!state.deepStars || r.rating === Number(state.deepStars))), state.deepSort);
  pane.append(node('p', `${nf(matched.length)} matching reviews`, 'muted'), reviewList(matched, state.deepPage, ui.page_detail, page => { state.deepPage = page; renderPage(); }, () => { resetDeepFilters(); renderPage(); })); root.append(pane); return root;
}
function opportunityCard(item, kind) {
  const scope = item.scopes[state.platform], stats = scope.stats, tone = kind === 'strengths' ? 'strength' : kind === 'feature_requests' ? 'request' : item.type;
  const card = node('article', undefined, `card opportunity ${tone}${stats.count < ui.few_reviews ? ' few' : ''}`); card.id = `insight-${item.id}`;
  const top = node('div', undefined, 'opp-top');
  const tag = node('p', undefined, `tag ${tone}`);
  if (kind === 'improvements') tag.append(icon(item.type === 'fix' ? 'fix' : 'explore'), node('span', item.type === 'fix' ? 'Fix' : 'Explore'));
  else tag.append(dotted(kind === 'strengths' ? 'Strength' : 'Request', kind === 'strengths' ? '--praise' : '--request'));
  const figure = node('p', undefined, 'opp-count'); figure.append(node('span', nf(stats.count), 'num'), node('span', 'reviews'));
  top.append(tag, figure); card.append(top, node('h3', scope.title), node('p', scope.desc || scope.text, 'opp-desc'));
  if (kind === 'improvements') { const row = node('div', undefined, 'meter-row'), track = node('span', undefined, 'meter'), fill = node('span', undefined, 'meter-fill'); fill.style.width = `${stats.pct_low_star ?? 0}%`; track.append(fill); row.append(track, node('span', pct(stats.pct_low_star), 'num'), node('span', 'at 1 to 2 stars')); card.append(row); }
  else if (kind === 'strengths') card.append(dotted(`${nf(stats.avg_rating, ui.rating_digits)} mean stars`, '--stars', 'p'));
  if (stats.count < ui.few_reviews) card.append(node('p', 'Few reviews in this view', 'few-note'));
  if (scope.next) card.append(nextStep(scope.next));
  const foot = node('div', undefined, 'opp-foot'), split = node('p', undefined, 'split');
  split.append(dotted(`Android ${nf(stats.android_count)}`, '--android'), dotted(`iOS ${nf(stats.ios_count)}`, '--ios'));
  const see = button('See reviews', () => openDrawer(item, see), 'see'); see.append(icon('arrow')); see.dataset.insightId = item.id; foot.append(split, see); card.append(foot); return card;
}
const median = values => { const sorted = [...values].sort((a, b) => a - b), mid = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2; };
function jumpToInsight(id) { const target = document.getElementById(`insight-${id}`); if (!target) return; target.classList.add('highlight'); target.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); target.querySelector('button').focus({preventScroll: true}); }
// Three lines under the matrix: what sits in each quadrant that calls for action, with a link to each card. Same medians as the chart.
function startHere(points, medianX, medianY) {
  const groups = [
    {title: 'Fix first', note: 'many reviews, mostly 1 to 2 stars', test: p => p.x >= medianX && p.y >= medianY},
    {title: 'Cheap and loud', note: 'few reviews, mostly 1 to 2 stars; usually operational', test: p => p.x < medianX && p.y >= medianY},
    {title: 'Product and pricing questions', note: 'many reviews, mixed stars', test: p => p.x >= medianX && p.y < medianY}];
  const list = node('ol', undefined, 'start-list');
  for (const group of groups) { const members = points.filter(group.test).sort((a, b) => b.x - a.x); if (!members.length) continue;
    const row = node('li'); const head = node('p', undefined, 'start-head'); head.append(node('strong', group.title), node('span', ` · ${group.note}`)); row.append(head);
    const chips = node('p', undefined, 'start-items'); members.forEach((p, i) => { const link = node('a', `${p.name} (${nf(p.x)})`); link.href = `#opportunities?${new URLSearchParams({platform: state.platform})}`; link.addEventListener('click', event => { event.preventDefault(); jumpToInsight(p.id); }); chips.append(link); if (i < members.length - ui.one) chips.append(node('span', ' · ')); }); row.append(chips); list.append(row); }
  const wrap = node('section', undefined, 'start-here'); wrap.append(node('h2', 'Start here'), node('p', 'Open "Next step" on any card for the check to run. Store reviews size the signal, not the problem.', 'muted'), list); return wrap;
}
function opportunities() {
  const root = node('div'), data = current(), s = data.stats; root.append(node('p', insights.evidence_note, 'evidence'));
  const improve = insights.improvements.map(item => ({item, scope: item.scopes[state.platform]})).filter(e => e.scope.stats.count).sort((a, b) => b.scope.stats.count - a.scope.stats.count || a.item.id.localeCompare(b.item.id));
  const lead = node('div', undefined, 'grid');
  if (improve.length > 1) {
    const points = improve.map(e => ({id: e.item.id, name: e.scope.title, short: e.item.short || short(e.scope.title), x: e.scope.stats.count, y: e.scope.stats.pct_low_star, type: e.item.type}));
    const tableRows = improve.map(e => [e.scope.title, e.item.type === 'fix' ? 'Fix' : 'Explore', nf(e.scope.stats.count), pct(e.scope.stats.pct_low_star)]);
    if (matchMedia('(max-width: 639px)').matches) {
      const card = node('section', undefined, 'chart-card span-12'), head = node('div', undefined, 'chart-header'), title = node('div'); title.append(node('h3', 'Size against pain'), node('p', 'Each area to improve, largest first, with its share at 1 to 2 stars')); head.append(title); card.append(head);
      const list = node('ol', undefined, 'rank-list');
      for (const e of improve) { const row = node('li'), track = node('span', undefined, 'meter'), fill = node('span', undefined, 'meter-fill'); fill.style.width = `${e.scope.stats.pct_low_star ?? 0}%`; track.append(fill);
        const line = node('div', undefined, 'rank-line'); line.append(button(e.scope.title, () => jumpToInsight(e.item.id), 'link'), node('span', nf(e.scope.stats.count), 'num')); const meter = node('div', undefined, 'meter-row'); meter.append(track, node('span', pct(e.scope.stats.pct_low_star), 'num')); row.append(line, meter); list.append(row); }
      card.append(list); lead.append(card);
    } else lead.append(chartCard({span: 12, kind: 'matrix', height: 520, title: 'Size against pain',
      subtitle: 'Each bubble is an area to improve: further right has more reviews, higher is angrier. The lines split the areas at the median size and the median pain, making four quadrants. Bubbles that would overlap are nudged just far enough apart to read; hover for exact values. Select a bubble to jump to its card',
      data: {points, medianX: median(points.map(p => p.x)), medianY: median(points.map(p => p.y)), onPick: jumpToInsight},
      table: {columns: ['Area', 'Type', 'Reviews', 'At 1 to 2 stars'], rows: tableRows}}));
    root.append(lead);
    root.append(startHere(points, median(points.map(p => p.x)), median(points.map(p => p.y))));
  }
  const categories = categoryEntries(data.categories);
  const hurting = [...categories].map(c => ({...c, complaints: c.by_label['Specific Complaint'], requests: c.by_label['Feature Request']})).filter(c => c.complaints + c.requests).sort((a, b) => (b.complaints + b.requests) - (a.complaints + a.requests));
  const score = [...categories].filter(c => c.pct_low_star !== null).sort((a, b) => b.pct_low_star - a.pct_low_star);
  const requests = insights.feature_requests.map(item => ({name: item.scopes[state.platform].title, ...item.scopes[state.platform].stats})).filter(r => r.count).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const grid = node('div', undefined, 'grid');
  grid.append(chartCard({span: 4, kind: 'stackedBars', height: rowsHeight(hurting.length, 28), title: 'Where complaints land', subtitle: 'Complaints and requests per category, by first label',
    data: {labels: hurting.map(categoryLabel), faded: hurting.map(isSmall), series: [{name: 'Complaints', token: '--complaint', values: hurting.map(c => c.complaints)}, {name: 'Requests', token: '--request', values: hurting.map(c => c.requests)}]},
    table: {columns: ['Category', 'Complaints', 'Requests'], rows: hurting.map(c => [c.name, nf(c.complaints), nf(c.requests)])}}),
  chartCard({span: 4, kind: 'bars', height: rowsHeight(score.length, 28), title: 'Pain score', subtitle: 'Share of each category\'s reviews at 1 to 2 stars',
    data: {labels: score.map(categoryLabel), values: score.map(c => c.pct_low_star), token: '--complaint', percent: true, faded: score.map(isSmall), notes: score.map(c => `${nf(c.low_star_count)} of ${nf(c.count)}`)},
    table: {columns: ['Category', 'At 1 to 2 stars', 'Reviews'], rows: score.map(c => [c.name, pct(c.pct_low_star), nf(c.count)])}}));
  if (requests.length) grid.append(chartCard({span: 4, kind: 'bars', height: rowsHeight(requests.length, 44), title: 'What people ask for', subtitle: `Feature requests by theme · themes can overlap · ${countNote(s.request_n)}`,
    data: {labels: requests.map(r => r.name), values: requests.map(r => r.count), token: '--request'},
    table: {columns: ['Theme', 'Reviews'], rows: requests.map(r => [r.name, nf(r.count)])}}));
  root.append(sectionHeading('Signal by category', `${platformName(state.platform)} · ${countNote(s.substantive)} substantive reviews`), grid);
  for (const [group, title, note] of [['improvements', 'Areas to improve', 'Largest first · the bar shows the share at 1 or 2 stars · each card has a next step'], ['feature_requests', 'Top feature requests', ''], ['strengths', 'What to protect', 'The things praised by name']]) {
    root.append(sectionHeading(title, note)); const cards = node('div', undefined, 'opportunity-grid');
    for (const item of [...insights[group]].filter(i => i.scopes[state.platform].stats.count).sort((a, b) => b.scopes[state.platform].stats.count - a.scopes[state.platform].stats.count || a.id.localeCompare(b.id))) cards.append(opportunityCard(item, group));
    if (!cards.childNodes.length) cards.append(node('p', 'No matching signals in this view.', 'muted')); root.append(cards);
  } return root;
}
function resetReviewFilters() { state.filters = {search: '', stars: '', label: '', category: '', competitor: '', language: '', from: '', to: '', substantive: false, sort: 'helpful'}; state.reviewPage = ui.one; }
async function reviewsTab() {
  const rows = await reviews(), root = node('div'), filters = node('div', undefined, 'filters'), f = state.filters;
  const listContainer = node('div');
  const filtered = () => sortReviews(rows.filter(r => (state.platform === 'all' || r.platform === state.platform) && (!f.search || r.search.includes(f.search.toLocaleLowerCase())) && (!f.stars || r.rating === Number(f.stars)) && (!f.label || r.labels.includes(f.label)) && (!f.category || r.categories.includes(f.category)) && (!f.competitor || r.competitors.includes(f.competitor)) && (!f.language || r.language === f.language) && (!f.from || r.date_utc >= f.from) && (!f.to || r.date_utc <= f.to) && (!f.substantive || r.categories.length)), f.sort);
  const refreshList = () => { const focus = rememberFocus(listContainer); const matched = filtered(); listContainer.replaceChildren(node('h2', `${nf(matched.length)} reviews match`, 'results-heading'), reviewList(matched, state.reviewPage, ui.page_reviews, page => { state.reviewPage = page; refreshList(); }, () => { resetReviewFilters(); renderPage(); })); restoreFocus(listContainer, focus); };
  const set = (key, value) => { f[key] = value; state.reviewPage = ui.one; refreshList(); };
  const search = node('input'); search.type = 'search'; search.placeholder = 'Search original, translation, or topic'; search.value = f.search; search.addEventListener('input', () => set('search', search.value)); filters.append(field('Search reviews', search, 'search'));
  filters.append(field('Stars', selectControl(starOptions(), f.stars, v => set('stars', v))));
  for (const [key, title, values] of [['label', 'Label', summary.meta.taxonomy.labels], ['category', 'Category', summary.meta.taxonomy.categories], ['competitor', 'Names a competitor', summary.meta.taxonomy.competitors], ['language', 'Language', [...new Set(rows.map(r => r.language))].sort()]]) filters.append(field(title, selectControl([['', key === 'competitor' ? 'Any or none' : `All ${key === 'category' ? 'categories' : `${key}s`}`], ...values.map(v => [v, key === 'language' ? languageName(v) : v])], f[key], v => set(key, v))));
  for (const [key, title] of [['from', 'From date'], ['to', 'To date']]) { const input = node('input'); input.type = 'date'; input.min = summary.meta.date_range.start; input.max = summary.meta.date_range.end; input.value = f[key]; input.addEventListener('change', () => set(key, input.value)); filters.append(field(title, input)); }
  const substantive = node('input'); substantive.type = 'checkbox'; substantive.checked = f.substantive; substantive.addEventListener('change', () => set('substantive', substantive.checked)); const check = node('label', undefined, 'checkbox'); check.append(substantive, node('span', 'Substantive only')); filters.append(check, field('Sort', selectControl(sortOptions(), f.sort, v => set('sort', v))), button('Clear filters', () => { resetReviewFilters(); renderPage(); }));
  root.append(filters); const downloads = node('div', undefined, 'header-actions'); for (const [file, title] of [['raw_reviews.csv', 'Reviews CSV'], ['annotated_reviews.csv', 'Annotated CSV']]) { const link = node('a', undefined, 'button'); link.append(icon('download'), node('span', title)); link.href = file; link.download = file; downloads.append(link); } root.append(downloads, listContainer); refreshList(); return root;
}
async function renderPage() {
  const focus = rememberFocus($('#content'));
  const epoch = renderEpoch += ui.one; setNavigation(); clearCharts();
  if (state.tab === 'deep-dive' || state.tab === 'reviews') $('#content').replaceChildren(node('div', undefined, 'skeleton'));
  try {
    const view = state.tab === 'overview' ? overview() : state.tab === 'opportunities' ? opportunities() : state.tab === 'deep-dive' ? await deepDive() : await reviewsTab();
    if (epoch !== renderEpoch) return; $('#content').replaceChildren(view); restoreFocus($('#content'), focus);
    // Arriving from a category link on a chart: start at the top of that category's page, with focus on its name.
    if (state.fromLink && state.tab === 'deep-dive') { state.fromLink = false; window.scrollTo({top: ui.zero}); const heading = $('#content .detail-header h2'); if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); } }
    if (state.chart && state.tab === 'overview') { jumpToChart(state.chart); state.chart = null; }
    if (state.takeaway && state.tab === 'overview') { jumpToTakeaway(state.takeaway); state.takeaway = null; }
    if (state.drawer) await renderDrawer();
    if (state.jump && state.tab === 'opportunities') { const target = document.getElementById(`insight-${state.jump}`); jumpToInsight(state.jump); state.jump = null; }
  } catch (error) { if (epoch === renderEpoch) $('#content').replaceChildren(errorView(error)); }
}
function backgroundInert(inert) { for (const element of document.querySelectorAll('body > :not(#drawer-backdrop):not(script)')) element.inert = inert; }
async function openDrawer(item, origin) {
  state.drawer = {item, origin, page: ui.one, stars: '', sort: 'helpful'}; $('#drawer-backdrop').hidden = false; document.body.classList.add('drawer-open'); backgroundInert(true); $('#drawer-close').focus(); await renderDrawer();
}
async function renderDrawer() {
  if (!state.drawer) return; const drawer = state.drawer;
  const focus = rememberFocus($('#drawer-content'));
  $('#drawer-title').textContent = drawer.item.scopes[state.platform].title;
  $('#drawer-content').replaceChildren(node('div', undefined, 'skeleton'));
  try {
    const rows = await reviews(); if (state.drawer !== drawer) return;
    const scope = drawer.item.scopes[state.platform], ids = new Set(scope.review_ids), matched = sortReviews(rows.filter(r => ids.has(r.review_id) && (!drawer.stars || r.rating === Number(drawer.stars))), drawer.sort);
    const platforms = node('div', undefined, 'segmented'); platforms.setAttribute('aria-label', 'Drawer platform');
    for (const platform of scopes) { const control = button(`${platformName(platform)} · ${nf(drawer.item.scopes[platform].stats.count)}`, () => changePlatform(platform)); control.setAttribute('aria-pressed', String(state.platform === platform)); platforms.append(control); }
    const toolbar = node('div', undefined, 'review-toolbar'); const set = (key, value) => { drawer[key] = value; drawer.page = ui.one; renderDrawer(); };
    toolbar.append(field('Stars', selectControl(starOptions(), drawer.stars, v => set('stars', v))), field('Sort', selectControl(sortOptions(), drawer.sort, v => set('sort', v))));
    const clear = () => { drawer.stars = ''; drawer.sort = 'helpful'; drawer.page = ui.one; renderDrawer(); };
    $('#drawer-content').replaceChildren(platforms, node('p', `${nf(matched.length)} matching reviews · ${platformName(state.platform)}`, 'note'), toolbar, reviewList(matched, drawer.page, ui.page_detail, page => { drawer.page = page; renderDrawer(); $('#drawer-close').focus(); }, clear)); restoreFocus($('#drawer-content'), focus);
    $('#drawer').scrollTop = ui.zero;
  } catch (error) { $('#drawer-content').replaceChildren(errorView(error)); }
}
function closeDrawer() {
  const drawer = state.drawer; if (!drawer) return; state.drawer = null; $('#drawer-backdrop').hidden = true; document.body.classList.remove('drawer-open'); backgroundInert(false);
  const origin = drawer.origin.isConnected ? drawer.origin : document.querySelector(`[data-insight-id="${CSS.escape(drawer.item.id)}"]`) || $(`[data-tab="${state.tab}"]`); origin.focus();
}
function initControls() {
  window.addEventListener('resize', checkReviewClamps);
  const clampObserver = new ResizeObserver(checkReviewClamps);
  clampObserver.observe($('#content')); clampObserver.observe($('#drawer-content'));
  for (const tab of document.querySelectorAll('[data-tab]')) tab.addEventListener('click', () => navigate(tab.dataset.tab));
  document.addEventListener('click', event => { if (event.target.closest?.('a[data-deep-link]')) state.fromLink = true; });
  $('#tabs').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const tabs = [...document.querySelectorAll('[data-tab]')]; let index = tabs.indexOf(document.activeElement);
    if (event.key === 'Home') index = ui.zero; else if (event.key === 'End') index = tabs.length - ui.one; else index = (index + (event.key === 'ArrowRight' ? ui.one : -ui.one) + tabs.length) % tabs.length;
    tabs.at(index).focus(); navigate(tabs.at(index).dataset.tab);
  });
  for (const platform of document.querySelectorAll('#platforms [data-platform]')) platform.addEventListener('click', () => changePlatform(platform.dataset.platform));
  window.addEventListener('hashchange', () => { hashState(); state.deepPage = state.reviewPage = ui.one; if (state.drawer) state.drawer.page = ui.one; renderPage(); });
  $('#drawer-close').addEventListener('click', closeDrawer); $('#drawer-backdrop').addEventListener('click', event => { if (event.target === $('#drawer-backdrop')) closeDrawer(); });
  document.addEventListener('keydown', event => { if (!state.drawer) return; if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); return; } if (event.key !== 'Tab') return;
    const focusable = [...$('#drawer').querySelectorAll('button:not(:disabled),a[href],input,select')].filter(el => el.getClientRects().length); const first = focusable.at(ui.zero), last = focusable.at(-ui.one);
    if (event.shiftKey && (document.activeElement === first || !$('#drawer').contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !$('#drawer').contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  });
  const media = matchMedia('(prefers-color-scheme: dark)');
  try { const theme = localStorage.getItem('review-theme'); if (['light', 'dark'].includes(theme)) document.documentElement.dataset.theme = theme; } catch { /* Theme still works without storage. */ }
  $('#theme').addEventListener('click', () => { const dark = document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && media.matches); const theme = dark ? 'light' : 'dark'; document.documentElement.dataset.theme = theme; try { localStorage.setItem('review-theme', theme); } catch { /* Storage is optional. */ } $('#theme').setAttribute('aria-label', `Switch to ${theme === 'light' ? 'dark' : 'light'} theme`); redrawCharts(); });
  media.addEventListener('change', () => { if (!document.documentElement.dataset.theme) redrawCharts(); });
}
async function boot() {
  try {
    summary = await fetchJSON('data/summary.json'); ui = summary.meta.ui; renderEpoch = ui.zero; state.deepPage = state.reviewPage = ui.one; resetReviewFilters();
    const meta = summary.meta; $('#subtitle').textContent = `${nf(summary.all.stats.count)} reviews · Google Play and App Store · ${dateText(meta.date_range.start)} to ${dateText(meta.date_range.end)}`;
    $('#footer').append(node('p', `Public Google Play and App Store reviews · Android ${nf(meta.platform_totals.android)} / iOS ${nf(meta.platform_totals.ios)} · ${dateText(meta.date_range.start)} to ${dateText(meta.date_range.end)} (UTC).`), node('p', `Labels and sentiment by an LLM, scored against ${nf(meta.gold.n)} hand-labeled reviews. Sentiment averages exclude ${nf(summary.all.stats.nonsense_count)} Nonsense reviews; store-star averages and review counts include them. Primary label agreement ${nf(meta.gold.primary_label.pct, ui.rating_digits)}% (${meta.gold.primary_label.matches}/${meta.gold.primary_label.n}); category agreement ${nf(meta.gold.primary_category.pct, ui.rating_digits)}% (${meta.gold.primary_category.matches}/${meta.gold.primary_category.n}).`), node('p', `Mobile apps only: ${meta.product.name}'s Mac and Windows apps have no store reviews. This is every review the stores served, not a fixed window. Apple's feed returns at most 500 reviews per country, so the largest iOS storefronts reach back less far than the smaller ones, and early weeks hold few reviews.`), node('p', `Independent, unofficial analysis of public store reviews. Not affiliated with ${meta.product.company}. Generated ${dateText(meta.generated_at.split('T').at(ui.zero))} from the source run timestamp.`));
    insights = await fetchJSON('data/insights.json'); hashState(); initControls(); await renderPage();
  } catch (error) { $('#content').replaceChildren(errorView(error)); }
}
boot();
