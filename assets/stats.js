/* The tracker's numbers, computed in the browser.
 *
 * This is the SECOND, independent implementation of track.py's compute(): the page does not
 * trust the numbers the tool wrote, it recomputes them from the items so a stale file can
 * never show a wrong "days behind". tests/test_parity.py runs both on the same data at
 * several moments and fails on any difference. Keep the two in step when either changes.
 *
 * The model, in one paragraph: every open item carries its share of Albert's day estimate
 * for its category. An item earns its days the moment he approves it. The plan is one
 * work-day per calendar day from the start, the categories in his order, so by any moment
 * the plan expects min(days elapsed, total work) to be done. Ahead/behind is done minus
 * that. Spare days are the days left to the deadline minus the work left.
 */
(function (root) {
  "use strict";
  var DAY = 86400000;
  var TZ = "Europe/Prague";

  // Offset of Prague from UTC, in minutes, at a UTC instant (handles summer/winter time).
  function pragueOffsetMin(utcMs) {
    var f = new Intl.DateTimeFormat("en-GB", {
      timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
    var p = {};
    f.formatToParts(new Date(utcMs)).forEach(function (x) { p[x.type] = x.value; });
    var asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
    return Math.round((asUtc - utcMs) / 60000);
  }

  // Prague wall-clock time -> UTC ms.
  function pragueToUtc(y, m, d, hh, mm) {
    var guess = Date.UTC(y, m - 1, d, hh, mm);
    var off = pragueOffsetMin(guess - 120 * 60000);
    var t = guess - off * 60000;
    var off2 = pragueOffsetMin(t);
    return off2 === off ? t : guess - off2 * 60000;
  }

  // An ISO date or datetime; a bare date means noon that day in Prague (same as track.py).
  function parseTime(s) {
    if (s == null) return NaN;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s).trim());
    if (m) return pragueToUtc(+m[1], +m[2], +m[3], 12, 0);
    return Date.parse(s);
  }

  // The deadline is the whole of that day: it ends at the next Prague midnight.
  function deadlineEnd(dateStr) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
    var next = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]) + DAY);
    return pragueToUtc(next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate(), 0, 0);
  }

  function sum(xs) { var t = 0; for (var k = 0; k < xs.length; k++) t += xs[k]; return t; }
  function w(i) { return i.weight == null ? 1 : i.weight; }

  var STATUSES = ["approved", "awaiting", "unchecked", "pixel", "in-progress", "todo"];

  function computeStats(plan, items, nowMs) {
    var start = parseTime(plan.start);
    var end = deadlineEnd(plan.deadline);
    var live = items.filter(function (i) { return i.status !== "removed"; });
    var weekAgo = nowMs - 7 * DAY;
    var cursor = 0, total = 0, earned = 0, earned7 = 0, approved7 = 0;
    var cats = plan.categories.map(function (c) {
      var its = live.filter(function (i) { return i.cat === c.id; });
      var work = sum(its.filter(function (i) { return !i.baseline; }).map(function (i) { return i.days; }));
      var done = 0;
      its.forEach(function (i) {
        if (i.status === "approved" && !i.baseline && i.approved_at) {
          var t = parseTime(i.approved_at);
          if (t <= nowMs) {
            done += i.days;
            if (t > weekAgo) { earned7 += i.days; approved7 += 1; }
          }
        }
      });
      var wAll = sum(its.map(w));
      var wOk = sum(its.filter(function (i) { return i.status === "approved"; }).map(w));
      var pct;
      if (c.pct_mode === "given") {
        var base = +(c.his_pct || 0);
        pct = base + (100 - base) * (work > 0 ? done / work : 1);
      } else {
        pct = wAll > 0 ? 100 * wOk / wAll : 0;
      }
      var by = {};
      STATUSES.forEach(function (s) { by[s] = 0; });
      its.forEach(function (i) { by[i.status] = (by[i.status] || 0) + 1; });
      var row = {
        id: c.id, pct: pct, work_days: work, done_days: done, left_days: work - done,
        items: its.length, approved: by.approved, by_status: by,
        plan_start: cursor, plan_end: cursor + work
      };
      cursor += work; total += work; earned += done;
      return row;
    });
    var elapsed = Math.max(0, (nowMs - start) / DAY);
    var planned = Math.min(elapsed, total);
    var left = total - earned;
    var toDeadline = (end - nowMs) / DAY;
    var pace7 = elapsed >= 1 ? earned7 / Math.min(7, elapsed) : null;
    var current = null;
    for (var k = 0; k < cats.length; k++) {
      if (cats[k].plan_start <= planned && planned < cats[k].plan_end) { current = cats[k].id; break; }
    }
    if (current === null && cats.length) current = planned >= total ? cats[cats.length - 1].id : cats[0].id;
    return {
      now: nowMs, start: start, deadline_end: end,
      total_work_days: total, earned_days: earned, planned_days: planned,
      variance_days: earned - planned, left_days: left, days_to_deadline: toDeadline,
      spare_days: toDeadline - left,
      launch_pct: total > 0 ? 100 * earned / total : 100,
      approved_7d: approved7, pace_7d: pace7,
      finish_at_plan_pace: nowMs + left * DAY,
      finish_at_recent_pace: pace7 && pace7 > 0 ? nowMs + (left / pace7) * DAY : null,
      current_phase: current, categories: cats
    };
  }

  // Cumulative work-days done, as steps, from the approvals in the item list.
  function earnedSeries(items, start) {
    var pts = items.filter(function (i) {
      return i.status === "approved" && !i.baseline && i.approved_at;
    }).map(function (i) { return { t: parseTime(i.approved_at), d: i.days }; })
      .filter(function (p) { return p.t >= start; })
      .sort(function (a, b) { return a.t - b.t; });
    var acc = 0, out = [{ t: start, v: 0 }];
    pts.forEach(function (p) { acc += p.d; out.push({ t: p.t, v: acc }); });
    return out;
  }

  var api = { computeStats: computeStats, parseTime: parseTime, deadlineEnd: deadlineEnd,
              earnedSeries: earnedSeries, pragueOffsetMin: pragueOffsetMin, DAY: DAY };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TrackerStats = api;
})(typeof window !== "undefined" ? window : globalThis);
