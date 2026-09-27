/* Party Ratz 4 Life — launch tracker page. Reads data/tracker.json (written only by track.py),
   recomputes every number with stats.js, and re-checks for new data every minute. All text
   from the data goes in through textContent. */
(function () {
  "use strict";
  var S = window.TrackerStats;
  var DAY = S.DAY;
  var SVGNS = "http://www.w3.org/2000/svg";
  var POLL_MS = 60000;
  var state = { data: null, fetchedAt: 0, failedAt: 0, filter: { q: "", cat: "all", status: "open" }, open: {}, showAll: false, table: false };

  var STATUS_LABEL = {
    approved: "Approved", awaiting: "Waiting for you", unchecked: "Not checked yet",
    pixel: "Old pixel art", "in-progress": "In progress", todo: "To do", removed: "Cut"
  };
  var ICON = {
    approved: '<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M4.6 8.3l2.2 2.2 4.6-4.8" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    awaiting: '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 4.6V8l2.3 1.5" stroke="currentColor" stroke-width="1.7" fill="none" stroke-linecap="round"/>',
    unchecked: '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.7" stroke-dasharray="2.4 2.1"/>',
    pixel: '<rect x="2" y="2" width="5.4" height="5.4" rx="1" fill="currentColor"/><rect x="8.6" y="8.6" width="5.4" height="5.4" rx="1" fill="currentColor"/><rect x="8.6" y="2" width="5.4" height="5.4" rx="1" fill="currentColor" opacity=".45"/><rect x="2" y="8.6" width="5.4" height="5.4" rx="1" fill="currentColor" opacity=".45"/>',
    "in-progress": '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 1.8a6.2 6.2 0 0 1 0 12.4z" fill="currentColor"/>',
    todo: '<circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.7"/>',
    removed: '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
  };
  var CHIP_ICON = {
    good: '<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M4.6 8.3l2.2 2.2 4.6-4.8" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    warning: '<path d="M8 1.6l6.8 12.2H1.2z" fill="currentColor"/><path d="M8 6v3.6M8 11.6v.1" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/>',
    critical: '<circle cx="8" cy="8" r="7" fill="currentColor"/><path d="M8 4.2v4.6M8 11.3v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
  };

  // ------------------------------------------------------------------ helpers
  function h(tag, props) {
    var n = document.createElement(tag);
    if (props) for (var k in props) {
      if (k === "class") n.className = props[k];
      else if (k === "html") n.innerHTML = props[k]; // only ever our own static markup
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), props[k]);
      else if (props[k] != null) n.setAttribute(k, props[k]);
    }
    for (var i = 2; i < arguments.length; i++) add(n, arguments[i]);
    return n;
  }
  function add(n, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(n, x); }); return; }
    n.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
  }
  function s(tag, attrs) {
    var n = document.createElementNS(SVGNS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  function icon(paths, cls) {
    var n = document.createElementNS(SVGNS, "svg");
    n.setAttribute("viewBox", "0 0 16 16"); n.setAttribute("aria-hidden", "true");
    if (cls) n.setAttribute("class", cls);
    n.innerHTML = paths;
    return n;
  }
  function badge(status) {
    return h("span", { class: "st " + status }, icon(ICON[status] || ICON.todo), STATUS_LABEL[status] || status);
  }
  function mount(id) { var n = document.getElementById(id); n.textContent = ""; return n; }
  var dFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Prague", day: "numeric", month: "short" });
  var dyFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Prague", day: "numeric", month: "short", year: "numeric" });
  var wFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Prague", weekday: "short", day: "numeric", month: "short" });
  var tFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Prague", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  function date(ms) { return dFmt.format(new Date(ms)); }
  function days(x, unit) {
    var a = Math.abs(x);
    var txt = a >= 10 ? String(Math.round(a)) : (Math.round(a * 10) / 10).toFixed(1).replace(/\.0$/, "");
    if (unit === false) return txt;
    return txt + (txt === "1" ? " day" : " days");
  }
  function pct(x) { return (x >= 99.5 && x < 100 ? Math.floor(x) : Math.round(x)) + "%"; }
  function rel(ms, now) {
    var m = Math.round((now - ms) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    var hr = Math.round(m / 60);
    if (hr < 24) return hr + " h ago";
    var d = Math.round(hr / 24);
    return d === 1 ? "yesterday" : d + " days ago";
  }
  function when(ms, now) {
    var sameDay = date(ms) === date(now);
    var yest = date(ms) === date(now - DAY);
    return (sameDay ? "Today" : yest ? "Yesterday" : wFmt.format(new Date(ms))) + " " + tFmt.format(new Date(ms));
  }
  function catName(id) {
    var c = state.data.plan.categories.filter(function (x) { return x.id === id; })[0];
    return c ? c.name : id;
  }
  function gameNo(g) { var m = /^7\.(\d+)/.exec(g); return m ? +m[1] : null; }

  // ------------------------------------------------------------------ data
  function load() {
    fetch("data/tracker.json?ts=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var changed = !state.data || d.generated_at !== state.data.generated_at;
        state.data = d; state.fetchedAt = Date.now(); state.failedAt = 0;
        if (changed) render(); else renderLive();
      })
      .catch(function () { state.failedAt = Date.now(); renderLive(); });
  }

  function render() {
    if (!state.data) return;
    var d = state.data, now = Date.now();
    var st = S.computeStats(d.plan, d.items, now);
    renderHero(st); renderKpis(st); renderNow(st); renderRecent(now); renderCats(st);
    renderTimeline(st); renderBurnup(st); renderGames(); renderAll(); renderFoot(st); renderLive();
  }

  function renderLive() {
    var live = document.getElementById("live"), txt = document.getElementById("live-text");
    if (!state.data) { txt.textContent = state.failedAt ? "Can't reach the tracker" : "Loading…"; live.className = "live" + (state.failedAt ? " offline" : ""); return; }
    var now = Date.now();
    var gen = S.parseTime(state.data.generated_at);
    if (state.failedAt) { live.className = "live offline"; txt.textContent = "Offline · data from " + rel(gen, now); return; }
    live.className = "live";
    txt.textContent = "Live · last change " + rel(gen, now);
  }

  // ------------------------------------------------------------------ hero + tiles
  function verdict(st) {
    if (st.spare_days < 0) return { cls: "critical", label: "Deadline at risk" };
    if (st.variance_days <= -0.5) return { cls: "warning", label: "Behind plan · deadline still safe" };
    if (st.variance_days >= 0.5) return { cls: "good", label: "Ahead of plan" };
    return { cls: "good", label: "On plan" };
  }
  function renderHero(st) {
    var n = mount("hero"), v = verdict(st), ahead = st.variance_days >= 0;
    var finish = st.finish_at_plan_pace, deadline = st.deadline_end - 1;
    n.appendChild(h("div", { class: "chip " + v.cls }, icon(CHIP_ICON[v.cls]), v.label));
    var zero = Math.abs(st.variance_days) < 0.05;
    n.appendChild(h("div", { class: "hero-figure" },
      zero ? "0" : (ahead ? "+" : "−") + days(st.variance_days, false),
      h("small", null, zero ? "days off the plan" :
        (days(st.variance_days, false) === "1" ? "day " : "days ") + (ahead ? "ahead" : "behind"))));
    n.appendChild(h("p", null, "You've done ", h("b", null, days(st.earned_days)), " of the ",
      h("b", null, days(st.total_work_days)), " of work in your plan; by now the plan expects ", h("b", null, days(st.planned_days)), "."));
    var gap = (st.deadline_end - finish) / DAY;
    n.appendChild(h("p", null, "At the plan's pace of one work-day a day you finish on ", h("b", null, wFmt.format(new Date(finish))),
      gap >= 0 ? [", ", h("b", null, days(gap)), " before the ", date(deadline), " deadline."]
               : [" — ", h("b", null, days(gap)), " after the ", date(deadline), " deadline."]));
  }
  function tile(label, value, unit, foot) {
    return h("div", { class: "tile" }, h("div", { class: "label" }, label),
      h("div", { class: "value" }, value, unit ? h("small", null, unit) : null), h("div", { class: "foot" }, foot));
  }
  function renderKpis(st) {
    var n = mount("kpis");
    n.appendChild(tile("Launch plan done", pct(st.launch_pct), null, days(st.earned_days, false) + " of " + days(st.total_work_days)));
    n.appendChild(tile("Until the deadline", String(Math.max(0, Math.ceil(st.days_to_deadline))), "days", dyFmt.format(new Date(st.deadline_end - 1))));
    n.appendChild(tile("Spare days", (st.spare_days < 0 ? "−" : "") + days(st.spare_days, false), null,
      st.spare_days < 0 ? "short of the deadline" : "left over at plan pace"));
    n.appendChild(tile("Approved this week", String(st.approved_7d), st.approved_7d === 1 ? "item" : "items",
      st.pace_7d != null ? days(st.pace_7d, false) + " work-days a day lately" : "since the tracker started"));
  }

  // ------------------------------------------------------------------ right now
  function renderNow(st) {
    var n = mount("now"), d = state.data;
    n.appendChild(h("h2", null, "Right now"));
    n.appendChild(h("p", { class: "sub" }, "Where the plan puts you today, and what's waiting on you."));
    var cur = st.categories.filter(function (c) { return c.id === st.current_phase; })[0];
    if (cur) {
      var len = Math.max(1, Math.round(cur.work_days));
      var dayIn = Math.min(Math.max(1, Math.floor(st.planned_days - cur.plan_start + 1e-6) + 1), len);
      n.appendChild(h("p", { class: "now-phase" }, "The plan has you on ", h("b", null, catName(cur.id)),
        cur.work_days >= 0.95 ? " — day " + dayIn + " of " + len + "." : "."));
      var groups = {};
      d.items.forEach(function (i) {
        if (i.cat !== cur.id || i.status === "approved" || i.status === "removed") return;
        groups[i.group] = (groups[i.group] || 0) + 1;
      });
      var top = Object.keys(groups).sort(function (a, b) { return groups[b] - groups[a] || a.localeCompare(b); }).slice(0, 5);
      if (top.length) {
        var ul = h("ul", { class: "list" });
        top.forEach(function (g) { ul.appendChild(h("li", null, h("span", { class: "grow" }, g), h("span", { class: "when" }, groups[g] + " to approve"))); });
        n.appendChild(ul);
      } else n.appendChild(h("p", { class: "empty" }, "Everything in this area is approved."));
    }
    var waiting = d.items.filter(function (i) { return i.status === "awaiting"; });
    var box = h("div", { class: "waiting" });
    if (waiting.length) {
      box.appendChild(h("div", null, h("b", null, String(waiting.length)), waiting.length === 1 ? " thing is" : " things are", " waiting for your verdict."));
      var names = waiting.slice(0, 3).map(function (i) { return i.group + ": " + i.name; });
      box.appendChild(h("div", { class: "where", style: "margin-top:4px;color:var(--ink-2);font-size:12.5px" }, names.join(" · ") + (waiting.length > 3 ? " · …" : "")));
      box.appendChild(h("button", { class: "linkbtn", type: "button", style: "margin-top:6px", onclick: function () {
        state.filter = { q: "", cat: "all", status: "awaiting" }; state.showAll = false; renderAll();
        document.getElementById("all").scrollIntoView({ behavior: "smooth", block: "start" });
      } }, "See them all"));
    } else box.appendChild(h("div", null, "Nothing is waiting for your verdict."));
    n.appendChild(box);
  }

  // ------------------------------------------------------------------ latest approvals
  function renderRecent(now) {
    var n = mount("recent"), d = state.data;
    n.appendChild(h("h2", null, "Latest approvals"));
    n.appendChild(h("p", { class: "sub" }, "Every time you say yes to something, it lands here."));
    var byId = {}; d.items.forEach(function (i) { byId[i.id] = i; });
    var evs = d.events.filter(function (e) { return e.act === "approve" || e.act === "reopen"; }).slice(-12).reverse();
    if (!evs.length) {
      n.appendChild(h("p", { class: "empty" }, "Nothing approved since the tracker started. Your next yes shows up here within a minute or two."));
      return;
    }
    var ul = h("ul", { class: "list" });
    evs.forEach(function (e) {
      var i = byId[e.id] || { name: e.id, group: "", cat: "" };
      var t = S.parseTime(e.ts);
      ul.appendChild(h("li", null,
        e.act === "approve" ? badge("approved") : badge("awaiting"),
        h("span", { class: "grow" },
          h("div", { class: "what" }, (e.act === "reopen" ? "Taken back: " : "") + i.name),
          h("div", { class: "where" }, [i.group, catName(i.cat)].filter(Boolean).join(" · ")),
          e.note ? h("div", { class: "quote" }, "“" + e.note + "”") : null),
        h("span", { class: "when" }, when(t, now))));
    });
    n.appendChild(ul);
  }

  // ------------------------------------------------------------------ categories
  function renderCats(st) {
    var n = mount("cats"), d = state.data;
    n.appendChild(h("h2", null, "Progress by area"));
    n.appendChild(h("p", { class: "sub" }, "The percentage is the share you've approved. Days are the work left from your own estimates. Tap an area to open it."));
    d.plan.categories.forEach(function (c) {
      var r = st.categories.filter(function (x) { return x.id === c.id; })[0];
      var open = !!state.open[c.id];
      var wrap = h("div", { class: "cat" + (open ? " open" : "") });
      var head = h("div", { class: "cat-head", role: "button", tabindex: "0", "aria-expanded": String(open) },
        h("div", { class: "cat-name" }, icon('<path d="M6 3.5L10.5 8 6 12.5" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>', "chev"), " ", c.name,
          st.current_phase === c.id ? h("span", { class: "phase-now" }, "now") : null),
        h("div", { class: "cat-pct" }, pct(r.pct)),
        h("div", { class: "meter", role: "img", "aria-label": c.name + " " + pct(r.pct) }, h("i", { style: "width:" + Math.max(0, Math.min(100, r.pct)).toFixed(2) + "%" })),
        h("div", { class: "cat-meta" },
          r.approved + " of " + r.items + " approved · " + (r.left_days > 0.005 ? days(r.left_days) + " of work left" : "no work left") +
          (r.by_status.awaiting ? " · " + r.by_status.awaiting + " waiting for you" : ""),
          c.his_pct != null ? h("span", { class: "est" }, " · you estimated " + c.his_pct + "% on " + date(S.parseTime(d.plan.estimates_given))) : null));
      function toggle() { state.open[c.id] = !state.open[c.id]; renderCats(S.computeStats(d.plan, d.items, Date.now())); }
      head.addEventListener("click", toggle);
      head.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      wrap.appendChild(head);
      var body = h("div", { class: "cat-body" });
      if (c.desc) body.appendChild(h("p", { class: "cat-desc" }, c.desc));
      var groups = {};
      d.items.forEach(function (i) {
        if (i.cat !== c.id || i.status === "removed") return;
        var g = groups[i.group] || (groups[i.group] = { n: 0, ok: 0, wait: 0 });
        g.n++; if (i.status === "approved") g.ok++; if (i.status === "awaiting") g.wait++;
      });
      Object.keys(groups).sort(groupSort).forEach(function (g) {
        var x = groups[g];
        body.appendChild(h("div", { class: "grp" }, h("span", null, g, x.wait ? h("span", { class: "st awaiting", style: "margin-left:6px" }, icon(ICON.awaiting), String(x.wait)) : null),
          h("div", { class: "meter" }, h("i", { style: "width:" + (100 * x.ok / x.n).toFixed(1) + "%" })),
          h("span", { class: "n" }, x.ok + "/" + x.n)));
      });
      wrap.appendChild(body);
      n.appendChild(wrap);
    });
  }
  function groupSort(a, b) {
    var ga = gameNo(a), gb = gameNo(b);
    if (ga != null && gb != null) return ga - gb;
    if (ga != null) return 1;
    if (gb != null) return -1;
    return a.localeCompare(b);
  }

  // ------------------------------------------------------------------ timeline (gantt)
  function renderTimeline(st) {
    var n = mount("timeline"), d = state.data;
    n.appendChild(h("h2", null, "Timeline"));
    n.appendChild(h("p", { class: "sub" }, "Your estimates laid end to end from the day the tracker started, one work-day per day, in the order you'll do them. The filled part of each bar is what you've approved."));
    n.appendChild(h("div", { class: "legend" },
      h("span", null, h("i", { class: "box", style: "background:var(--accent-track)" }), "Planned"),
      h("span", null, h("i", { class: "box", style: "background:var(--accent)" }), "Approved"),
      h("span", null, h("i", { style: "background:var(--ink);width:2px;height:12px" }), "Today"),
      h("span", null, h("i", { class: "box", style: "background:var(--surface-2);border:1px solid var(--border)" }), "Spare days")));
    var wrap = h("div", { class: "chart" }); n.appendChild(wrap);
    var W = Math.max(300, wrap.clientWidth || n.clientWidth - 36);
    var labelW = W < 560 ? 96 : 150, x0 = labelW, x1 = W - 10;
    var rows = st.categories.length + 1, rowH = 26, top = 22, H = top + rows * rowH + 22;
    var t0 = st.start, t1 = st.deadline_end;
    function X(t) { return x0 + (t - t0) / (t1 - t0) * (x1 - x0); }
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Timeline of the plan from start to deadline" });
    // month + week grid
    var first = new Date(t0), ticks = [];
    for (var k = 0; k < 4; k++) {
      var m = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + k, 1));
      var mt = S.parseTime(m.toISOString().slice(0, 10)) - 12 * 3600000;
      if (mt > t0 && mt < t1) ticks.push(mt);
    }
    var crowded = false;
    ticks.forEach(function (t) {
      svg.appendChild(s("line", { x1: X(t), x2: X(t), y1: top - 4, y2: H - 20, class: "gridline" }));
      var tx = s("text", { x: X(t) + 3, y: top - 8, class: "tick" }); tx.textContent = date(t); svg.appendChild(tx);
      if (X(t) - x0 < 52) crowded = true;
    });
    if (!crowded) { var st0 = s("text", { x: x0, y: top - 8, class: "tick" }); st0.textContent = date(t0); svg.appendChild(st0); }
    st.categories.forEach(function (c, idx) {
      var y = top + idx * rowH;
      if (c.id === st.current_phase) svg.appendChild(s("rect", { x: 0, y: y + 1, width: W, height: rowH - 2, rx: 6, fill: "var(--accent-wash)" }));
      var lab = s("text", { x: 6, y: y + rowH / 2 + 4 }); lab.textContent = shortName(catName(c.id), labelW); svg.appendChild(lab);
      var a = X(t0 + c.plan_start * DAY), b = X(t0 + c.plan_end * DAY), wdt = Math.max(3, b - a);
      svg.appendChild(s("rect", { x: a, y: y + 7, width: wdt, height: rowH - 14, rx: 3, fill: "var(--accent-track)" }));
      var frac = c.work_days > 0 ? c.done_days / c.work_days : 1;
      if (frac > 0) svg.appendChild(s("rect", { x: a, y: y + 7, width: Math.max(2, wdt * frac), height: rowH - 14, rx: 3, fill: "var(--accent)" }));
      var title = s("title", {}); title.textContent = catName(c.id) + ": " + date(t0 + c.plan_start * DAY) + " – " + date(t0 + c.plan_end * DAY) +
        " · " + days(c.work_days) + " planned, " + pct(100 * frac) + " approved"; svg.lastChild.appendChild(title);
    });
    // spare row
    var ys = top + st.categories.length * rowH, sa = X(t0 + st.total_work_days * DAY);
    var spLab = s("text", { x: 6, y: ys + rowH / 2 + 4 }); spLab.textContent = "Spare days"; svg.appendChild(spLab);
    if (x1 - sa > 1) svg.appendChild(s("rect", { x: sa, y: ys + 7, width: x1 - sa, height: rowH - 14, rx: 3, fill: "var(--surface-2)", stroke: "var(--border)" }));
    // today + deadline
    var xt = X(Math.min(Math.max(st.now, t0), t1));
    svg.appendChild(s("line", { x1: xt, x2: xt, y1: top - 2, y2: H - 18, stroke: "var(--ink)", "stroke-width": 1.5 }));
    var tl = s("text", { x: Math.min(xt + 3, W - 40), y: H - 6, style: "fill:var(--ink);font-weight:600" }); tl.textContent = "today"; svg.appendChild(tl);
    svg.appendChild(s("line", { x1: x1, x2: x1, y1: top - 4, y2: H - 18, stroke: "var(--critical)", "stroke-width": 1.5 }));
    var dl = s("text", { x: x1, y: H - 6, "text-anchor": "end", style: "fill:var(--critical-ink);font-weight:600" }); dl.textContent = date(t1 - 1); svg.appendChild(dl);
    wrap.appendChild(svg);
  }
  function shortName(name, labelW) {
    if (labelW >= 150 || name.length <= 13) return name;
    return name.replace("Secondary art", "Secondary art").replace("Sound effects", "Sound FX").replace("Playtesting", "Playtesting");
  }

  // ------------------------------------------------------------------ burn-up
  function renderBurnup(st) {
    var n = mount("burnup"), d = state.data;
    n.appendChild(h("h2", null, "Work done vs. the plan"));
    n.appendChild(h("p", { class: "sub" }, "Work-days earned by your approvals, against the plan. When the blue line is above the grey one, you're ahead."));
    n.appendChild(h("div", { class: "legend" },
      h("span", null, h("i", { style: "background:var(--plan)" }), "Plan"),
      h("span", null, h("i", { style: "background:var(--accent)" }), "Done")));
    var wrap = h("div", { class: "chart chart-wrap" }); n.appendChild(wrap);
    var W = Math.max(300, wrap.clientWidth || n.clientWidth - 36), H = W < 560 ? 210 : 260;
    var L = 34, R = 44, T = 10, B = 24;
    var t0 = st.start, t1 = st.deadline_end, ymax = niceMax(st.total_work_days);
    function X(t) { return L + (t - t0) / (t1 - t0) * (W - L - R); }
    function Y(v) { return T + (1 - v / ymax) * (H - T - B); }
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Work-days done against the plan over time" });
    niceTicks(ymax).forEach(function (v) {
      svg.appendChild(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: v === 0 ? "axisline" : "gridline" }));
      var tx = s("text", { x: L - 6, y: Y(v) + 4, "text-anchor": "end", class: "tick" }); tx.textContent = String(v); svg.appendChild(tx);
    });
    var first = new Date(t0), crowdB = false;
    for (var k = 0; k < 4; k++) {
      var m = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + k, 1));
      var mt = S.parseTime(m.toISOString().slice(0, 10)) - 12 * 3600000;
      if (mt > t0 && mt < t1) { var tx2 = s("text", { x: X(mt), y: H - 6, "text-anchor": "middle", class: "tick" }); tx2.textContent = date(mt); svg.appendChild(tx2); if (X(mt) - L < 60) crowdB = true; }
    }
    if (!crowdB) { var tStart = s("text", { x: L, y: H - 6, class: "tick" }); tStart.textContent = date(t0); svg.appendChild(tStart); }
    var tEnd = s("text", { x: W - R, y: H - 6, "text-anchor": "end", class: "tick", style: "fill:var(--critical-ink)" }); tEnd.textContent = date(t1 - 1); svg.appendChild(tEnd);
    svg.appendChild(s("line", { x1: X(t1), x2: X(t1), y1: T, y2: H - B, stroke: "var(--critical)", "stroke-width": 1 }));
    var tp = t0 + st.total_work_days * DAY;
    svg.appendChild(s("path", { d: "M" + X(t0) + "," + Y(0) + "L" + X(Math.min(tp, t1)) + "," + Y(Math.min(st.total_work_days, (Math.min(tp, t1) - t0) / DAY)) + "L" + X(t1) + "," + Y(Math.min(st.total_work_days, (t1 - t0) / DAY)),
      fill: "none", stroke: "var(--plan)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    var series = S.earnedSeries(d.items, t0).filter(function (p) { return p.t <= st.now; });
    var path = "M" + X(t0) + "," + Y(0), last = 0;
    series.forEach(function (p) { path += "L" + X(p.t) + "," + Y(last) + "L" + X(p.t) + "," + Y(p.v); last = p.v; });
    var tNow = Math.min(st.now, t1);
    path += "L" + X(tNow) + "," + Y(last);
    svg.appendChild(s("path", { d: path, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    svg.appendChild(s("circle", { cx: X(tNow), cy: Y(last), r: 4.5, fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2 }));
    var lab = s("text", { x: X(tNow) + 8, y: Y(last) - 6, style: "fill:var(--ink);font-weight:600" }); lab.textContent = "Done " + days(last, false); svg.appendChild(lab);
    var lp = s("text", { x: X(Math.min(tp, t1)) - 4, y: Y(Math.min(st.total_work_days, (Math.min(tp, t1) - t0) / DAY)) - 8, "text-anchor": "end" }); lp.textContent = "Plan " + days(st.total_work_days, false); svg.appendChild(lp);
    // crosshair
    var cross = s("line", { y1: T, y2: H - B, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" }); svg.appendChild(cross);
    var hit = s("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent", tabindex: "0" }); svg.appendChild(hit);
    wrap.appendChild(svg);
    var tip = h("div", { class: "tip" }); wrap.appendChild(tip);
    function doneAt(t) { var v = 0; series.forEach(function (p) { if (p.t <= t) v = p.v; }); return v; }
    function planAt(t) { return Math.max(0, Math.min(st.total_work_days, (t - t0) / DAY)); }
    function show(clientX) {
      var r = svg.getBoundingClientRect(), px = (clientX - r.left) * (W / r.width);
      var t = t0 + (Math.min(Math.max(px, L), W - R) - L) / (W - L - R) * (t1 - t0);
      cross.setAttribute("x1", X(t)); cross.setAttribute("x2", X(t)); cross.setAttribute("visibility", "visible");
      tip.textContent = "";
      tip.appendChild(h("div", { class: "t-date" }, wFmt.format(new Date(t))));
      tip.appendChild(h("div", { class: "t-row" }, h("i", { style: "background:var(--plan)" }), h("b", null, days(planAt(t), false)), "Plan"));
      if (t <= st.now) tip.appendChild(h("div", { class: "t-row" }, h("i", { style: "background:var(--accent)" }), h("b", null, days(doneAt(t), false)), "Done"));
      var left = (X(t) / W) * r.width;
      tip.style.left = Math.min(Math.max(0, left - 80), r.width - 170) + "px"; tip.style.top = "0px"; tip.classList.add("show");
    }
    hit.addEventListener("pointermove", function (e) { show(e.clientX); });
    hit.addEventListener("pointerdown", function (e) { show(e.clientX); });
    hit.addEventListener("pointerleave", function () { tip.classList.remove("show"); cross.setAttribute("visibility", "hidden"); });
    hit.addEventListener("focus", function () { var r = svg.getBoundingClientRect(); show(r.left + (X(tNow) / W) * r.width); });
    hit.addEventListener("blur", function () { tip.classList.remove("show"); cross.setAttribute("visibility", "hidden"); });
    // table view
    var btn = h("button", { class: "linkbtn", type: "button", style: "margin-top:8px" }, state.table ? "Hide the table" : "Show as a table");
    btn.addEventListener("click", function () { state.table = !state.table; renderBurnup(S.computeStats(d.plan, d.items, Date.now())); });
    n.appendChild(btn);
    if (state.table) {
      var tb = h("table", { class: "data" }, h("thead", null, h("tr", null, h("th", null, "Day"), h("th", { class: "num" }, "Plan"), h("th", { class: "num" }, "Done"), h("th", { class: "num" }, "Ahead / behind"))));
      var body = h("tbody");
      for (var t = t0; t <= Math.min(st.now, t1) + 1; t += DAY) {
        var tt = Math.min(t, st.now), p = planAt(tt), dn = doneAt(tt);
        body.appendChild(h("tr", null, h("td", null, wFmt.format(new Date(tt))), h("td", { class: "num" }, p.toFixed(1)), h("td", { class: "num" }, dn.toFixed(1)), h("td", { class: "num" }, (dn - p >= 0 ? "+" : "−") + Math.abs(dn - p).toFixed(1))));
      }
      tb.appendChild(body);
      n.appendChild(h("div", { class: "scroll-x", style: "margin-top:10px" }, tb));
    }
  }
  function niceMax(v) { var steps = [5, 10, 20, 25, 50, 60, 75, 100]; for (var k = 0; k < steps.length; k++) if (steps[k] >= v) return steps[k]; return Math.ceil(v / 50) * 50; }
  function niceTicks(max) { var step = max <= 10 ? 2 : max <= 25 ? 5 : max <= 60 ? 10 : 25, out = []; for (var v = 0; v <= max + 1e-9; v += step) out.push(v); return out; }

  // ------------------------------------------------------------------ minigames
  function renderGames() {
    var n = mount("games"), d = state.data;
    n.appendChild(h("h2", null, "Minigames"));
    n.appendChild(h("p", { class: "sub" }, "Every minigame: its mechanics, how much of its art (rats, props, backgrounds, HUD) and its sound you've approved, and the work left in it. Art made by an agent counts only after your yes."));
    var games = {};
    function blank() { return { n: 0, ok: 0, wait: 0 }; }
    d.items.forEach(function (i) {
      if (i.status === "removed") return;
      var key = i.game || (gameNo(i.group) != null ? i.group : null);
      if (!key) return;
      var g = games[key] || (games[key] = { no: gameNo(key), mech: blank(), art: blank(), snd: blank(), left: 0 });
      var b = i.cat === "mechanics" ? g.mech : (i.cat === "art-secondary" || i.cat === "art-primary") ? g.art :
              (i.cat === "music" || i.cat === "sfx") ? g.snd : null;
      if (b) { b.n++; if (i.status === "approved") b.ok++; if (i.status === "awaiting") b.wait++; }
      if (i.status !== "approved" && !i.baseline) g.left += i.days || 0;
    });
    var keys = Object.keys(games).filter(function (k) { return games[k].no != null; }).sort(function (a, b) { return games[a].no - games[b].no; });
    if (!keys.length) { n.appendChild(h("p", { class: "empty" }, "No minigame items yet.")); return; }
    function meterCell(b) {
      if (b.n === 0) return h("span", { class: "st todo" }, "—");
      return h("div", { class: "cell-meter", title: b.ok + " of " + b.n + " approved" + (b.wait ? ", " + b.wait + " waiting for you" : "") },
        h("div", { class: "meter" }, h("i", { style: "width:" + (100 * b.ok / b.n).toFixed(1) + "%" })), h("span", null, b.ok + "/" + b.n));
    }
    var list = h("div", { class: "glist" });
    list.appendChild(h("div", { class: "grow-head" }, h("span", null, "Game"), h("span", null, "Mechanics"), h("span", null, "Art"), h("span", null, "Sound & music"), h("span", { class: "num" }, "Work left")));
    keys.forEach(function (k) {
      var g = games[k], name = k.replace(/^7\.\d+\s*/, "");
      var mech = g.mech.n === 0 ? h("span", { class: "st todo" }, "—") :
        g.mech.ok === g.mech.n ? badge("approved") :
        h("span", { class: "st " + (g.mech.wait ? "awaiting" : "todo") }, icon(ICON[g.mech.wait ? "awaiting" : "todo"]), (g.mech.n - g.mech.ok) + " open");
      list.appendChild(h("div", { class: "grow-row" },
        h("div", { class: "g-name" }, name, h("small", null, "game " + g.no)),
        h("div", { class: "g-cell", "data-label": "Mechanics" }, mech),
        h("div", { class: "g-cell", "data-label": "Art" }, meterCell(g.art)),
        h("div", { class: "g-cell", "data-label": "Sound & music" }, meterCell(g.snd)),
        h("div", { class: "g-left num" }, g.left > 0.005 ? days(g.left) + " left" : "done")));
    });
    n.appendChild(list);
  }

  // ------------------------------------------------------------------ every item
  function renderAll() {
    var n = mount("all"), d = state.data, f = state.filter;
    n.appendChild(h("h2", null, "Every item"));
    n.appendChild(h("p", { class: "sub" }, "Search anything. Only your own yes turns an item green."));
    var q = h("input", { type: "search", placeholder: "Search: sumo, tail, menu…", value: f.q, "aria-label": "Search items" });
    var sel = h("select", { "aria-label": "Status" });
    [["open", "Not approved yet"], ["awaiting", "Waiting for you"], ["approved", "Approved"], ["all", "Everything"]].forEach(function (o) {
      var op = h("option", { value: o[0] }, o[1]); if (o[0] === f.status) op.selected = true; sel.appendChild(op);
    });
    var t;
    q.addEventListener("input", function () { clearTimeout(t); t = setTimeout(function () { state.filter.q = q.value; state.showAll = false; drawList(); }, 160); });
    sel.addEventListener("change", function () { state.filter.status = sel.value; state.showAll = false; drawList(); });
    n.appendChild(h("div", { class: "filters" }, q, sel));
    var chips = h("div", { class: "chips", role: "group", "aria-label": "Area" });
    [["all", "All areas"]].concat(d.plan.categories.map(function (c) { return [c.id, c.name]; })).forEach(function (c) {
      var b = h("button", { type: "button", "aria-pressed": String(f.cat === c[0]) }, c[1]);
      b.addEventListener("click", function () { state.filter.cat = c[0]; state.showAll = false; renderAll(); });
      chips.appendChild(b);
    });
    n.appendChild(chips);
    var listBox = h("div"); n.appendChild(listBox);
    function drawList() {
      listBox.textContent = "";
      var words = norm(state.filter.q).split(" ").filter(Boolean);
      var hits = d.items.filter(function (i) {
        if (state.filter.cat !== "all" && i.cat !== state.filter.cat) return false;
        var stf = state.filter.status;
        if (stf === "open" && (i.status === "approved" || i.status === "removed")) return false;
        if (stf === "awaiting" && i.status !== "awaiting") return false;
        if (stf === "approved" && i.status !== "approved") return false;
        if (!words.length) return true;
        var hay = norm(i.name + " " + i.group + " " + catName(i.cat) + " " + (i.note || ""));
        return words.every(function (w) { return hay.indexOf(w) >= 0; });
      });
      var order = {}; d.plan.categories.forEach(function (c, k) { order[c.id] = k; });
      hits.sort(function (a, b) { return order[a.cat] - order[b.cat] || groupSort(a.group, b.group) || a.name.localeCompare(b.name); });
      listBox.appendChild(h("div", { class: "empty" }, hits.length + (hits.length === 1 ? " item" : " items")));
      var cap = state.showAll ? hits.length : Math.min(hits.length, 150), lastCat = null, lastGroup = null;
      for (var k = 0; k < cap; k++) {
        var i = hits[k];
        if (i.cat !== lastCat) { listBox.appendChild(h("div", { class: "icat" }, catName(i.cat))); lastCat = i.cat; lastGroup = null; }
        if (i.group !== lastGroup) { listBox.appendChild(h("div", { class: "igroup" }, i.group)); lastGroup = i.group; }
        listBox.appendChild(h("div", { class: "item" }, h("span", { class: "nm" }, i.name), badge(i.status),
          i.note ? h("div", { class: "nt" }, i.note) : null));
      }
      if (cap < hits.length) {
        var more = h("button", { class: "linkbtn more", type: "button" }, "Show all " + hits.length);
        more.addEventListener("click", function () { state.showAll = true; drawList(); });
        listBox.appendChild(more);
      }
    }
    drawList();
  }
  function norm(x) { return String(x || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }

  // ------------------------------------------------------------------ footer
  function renderFoot(st) {
    var n = mount("foot"), d = state.data;
    var est = d.plan.categories.map(function (c) { return c.name.toLowerCase() + " " + days(c.days); }).join(", ");
    n.appendChild(h("p", null, h("b", null, "How this works. "), "When you approve something in a session, the developer agent records it with the tracker's tool and it is published straight away; this page checks for news every minute."));
    n.appendChild(h("p", null, "Only your own yes completes an item. Something an agent made that you haven't checked counts as not done."));
    n.appendChild(h("p", null, "The plan uses your estimates from 27 Sep 2026: " + est + ". Items added later carry their own days, so new work pushes the finish out instead of hiding."));
    n.appendChild(h("p", null, "Data written " + dyFmt.format(new Date(S.parseTime(d.generated_at))) + " at " + tFmt.format(new Date(S.parseTime(d.generated_at))) + "."));
  }

  // ------------------------------------------------------------------ theme + boot
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("prt-theme"); } catch (e) { }
    if (saved === "dark" || saved === "light") document.documentElement.setAttribute("data-theme", saved);
    document.getElementById("theme").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme") ||
        (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("prt-theme", next); } catch (e) { }
      render();
    });
  }
  var rs;
  window.addEventListener("resize", function () { clearTimeout(rs); rs = setTimeout(function () { if (state.data) { var st = S.computeStats(state.data.plan, state.data.items, Date.now()); renderTimeline(st); renderBurnup(st); } }, 150); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  initTheme();
  load();
  setInterval(function () { load(); if (state.data) render(); }, POLL_MS);
})();
