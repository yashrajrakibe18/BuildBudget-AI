"""Dependency validation, critical path (CPM) and calendar scheduling.

`critical_path` reports WORKING duration along the critical path. `calendar_plan`
maps that onto real dates, honouring working days and dependency gaps, so a
"9 day" critical path can still finish three weeks later. Overdue detection uses
the calendar plan, never the raw working duration.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date, timedelta


def topo_order(tasks: list[dict]) -> list[int]:
    ids = {t["id"] for t in tasks}
    indeg = {t["id"]: 0 for t in tasks}
    out = defaultdict(list)
    for t in tasks:
        for d in t.get("deps", []):
            if d not in ids:
                raise ValueError(f"Task {t.get('name') or t['id']} depends on a task that no longer exists")
            if d == t["id"]:
                raise ValueError(f"Task '{t.get('name') or t['id']}' depends on itself")
            out[d].append(t["id"])
            indeg[t["id"]] += 1
    q = deque(sorted(i for i, n in indeg.items() if n == 0))
    order = []
    while q:
        n = q.popleft()
        order.append(n)
        for m in out[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(order) != len(tasks):
        raise ValueError("This dependency chain is circular — remove the loop to schedule the project")
    return order


def critical_path(tasks: list[dict]) -> dict:
    if not tasks:
        return {"order": [], "critical_path": [], "total_duration_days": 0, "tasks": {},
                "note": "No tasks scheduled yet."}
    by = {t["id"]: t for t in tasks}
    order = topo_order(tasks)
    es, ef = {}, {}
    for i in order:
        es[i] = max((ef[d] for d in by[i].get("deps", [])), default=0)
        ef[i] = es[i] + by[i]["duration"]
    total = max(ef.values())
    succ = defaultdict(list)
    for t in tasks:
        for d in t.get("deps", []):
            succ[d].append(t["id"])
    ls, lf = {}, {}
    for i in reversed(order):
        lf[i] = min((ls[s] for s in succ[i]), default=total)
        ls[i] = lf[i] - by[i]["duration"]
    slack = {i: ls[i] - es[i] for i in order}
    crit = [i for i in order if slack[i] == 0]
    return {
        "order": order, "critical_path": crit, "total_duration_days": total,
        "critical_path_names": [by[i].get("name", str(i)) for i in crit],
        "tasks": {i: {"es": es[i], "ef": ef[i], "slack": slack[i], "critical": slack[i] == 0,
                      "name": by[i].get("name", str(i)), "duration": by[i]["duration"]} for i in order},
        "note": ("Indicative working duration from your entered durations. It is not a guaranteed "
                 "completion date and excludes weather, approvals and procurement lead time."),
    }


def _next_working_day(d: date, working_days: set[int], holidays: set[date]) -> date:
    guard = 0
    while (d.weekday() not in working_days) or (d in holidays):
        d += timedelta(days=1)
        guard += 1
        if guard > 400:
            raise ValueError("No working day found in the next 400 days — check the working-day pattern")
    return d


def _add_working_days(start: date, days: int, working_days: set[int], holidays: set[date]) -> date:
    """Finish date for `days` working days starting on `start` (inclusive)."""
    remaining = max(1, int(days))
    d = _next_working_day(start, working_days, holidays)
    while remaining > 0:
        remaining -= 1
        if remaining == 0:
            return d
        d = _next_working_day(d + timedelta(days=1), working_days, holidays)
    return d


def calendar_plan(tasks: list[dict], project_start: date | None = None, *,
                  working_days: set[int] | None = None, holidays: list[date] | None = None,
                  today: date | None = None) -> dict:
    """tasks: [{id, name, duration(days), deps, start_date?, progress, milestone?}]"""
    working_days = working_days if working_days is not None else {0, 1, 2, 3, 4}
    holidays_set = set(holidays or [])
    today = today or date.today()
    if not tasks:
        return {"rows": [], "milestones": [], "critical_path_names": [], "project_start": project_start,
                "project_finish": None, "total_duration_days": 0, "working_days": sorted(working_days),
                "note": "No tasks scheduled yet."}
    cpm = critical_path(tasks)
    by = {t["id"]: t for t in tasks}

    starts: dict[int, date] = {}
    finishes: dict[int, date] = {}
    for tid in cpm["order"]:
        t = by[tid]
        ready = project_start or today
        if t.get("start_date"):
            ready = max(ready, t["start_date"])
        for dep in t.get("deps", []):
            dep_finish = finishes[dep]
            ready = max(ready, _next_working_day(dep_finish + timedelta(days=1), working_days, holidays_set))
        start = _next_working_day(ready, working_days, holidays_set)
        starts[tid] = start
        finishes[tid] = _add_working_days(start, t["duration"], working_days, holidays_set)

    finish = max(finishes.values())
    rows = []
    for tid in cpm["order"]:
        t = by[tid]
        info = cpm["tasks"][tid]
        planned_end = finishes[tid]
        late = planned_end < today and (t.get("progress") or 0) < 100
        rows.append({
            "id": tid, "name": t.get("name", str(tid)), "duration_days": t["duration"],
            "start": starts[tid].isoformat(), "end": planned_end.isoformat(),
            "es": info["es"], "ef": info["ef"], "slack_days": info["slack"],
            "critical": info["critical"], "progress": t.get("progress", 0),
            "priority": t.get("priority", "normal"), "assignee": t.get("assignee", ""),
            "milestone": bool(t.get("milestone")),
            "deps": [by[d].get("name", str(d)) for d in t.get("deps", [])],
            "overdue": late,
            "days_late": (today - planned_end).days if late else 0,
            "variance_days": (today - planned_end).days if late else 0,
        })
    span = (finish - (project_start or min(starts.values()))).days + 1
    return {
        "rows": rows,
        "milestones": [r for r in rows if r["milestone"]],
        "critical_path_names": cpm["critical_path_names"],
        "project_start": (project_start or min(starts.values())).isoformat(),
        "project_finish": finish.isoformat(),
        "calendar_span_days": span,
        "total_duration_days": cpm["total_duration_days"],
        "working_days": sorted(working_days),
        "overdue": [r for r in rows if r["overdue"]],
        "note": ("Calendar dates assume a 5-day working week and the durations you entered. "
                 "The critical path shows the sequence that controls the finish date."),
    }


def schedule_variance(rows: list[dict], progress_by_id: dict[int, float] | None = None) -> dict:
    """Compare planned finish against actual completion / today."""
    today = date.today()
    progress_by_id = progress_by_id or {}
    late = [r for r in rows if r["overdue"]]
    completed = [r for r in rows if (progress_by_id.get(r["id"], r["progress"]) or 0) >= 100]
    planned = sum(r["duration_days"] for r in rows) or 1
    done = sum(r["duration_days"] * (progress_by_id.get(r["id"], r["progress"]) or 0) / 100 for r in rows)
    return {
        "planned_days": planned,
        "completed_equivalent_days": round(done, 1),
        "progress_pct": round(done / planned * 100, 1),
        "late_tasks": len(late),
        "total_late_days": sum(r["days_late"] for r in late),
        "completed_tasks": len(completed),
        "as_of": today.isoformat(),
    }
