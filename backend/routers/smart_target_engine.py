"""Pure IST personal sequence calculations. No calendar targets or revision writes."""
from copy import deepcopy
from datetime import date, timedelta
from fastapi import HTTPException


def snapshot(plan, sid, today, now):
    days = []
    for day in plan['days']:
        tasks = []
        for i, entry in enumerate(day['entries']):
            tasks.append({**deepcopy(entry), 'id': f"{plan['id']}:d{day['day']}:t{i+1}",
                          'mandatory': entry.get('mandatory', True)})
        if not any(t['mandatory'] for t in tasks):
            raise HTTPException(400, 'Every personal day needs at least one mandatory task.')
        days.append({'day': day['day'], 'tasks': tasks, 'completions': {}})
    return {'_id': f"{sid}:{plan['id']}", 'studentId': sid, 'planId': plan['id'],
            'name': plan['name'], 'startDate': today.isoformat(), 'startedAt': now,
            'days': days, 'includedBackupDays': plan.get('includedBackupDays', 0),
            'revisionBudgetMinutes': plan.get('revisionBudgetMinutes', 30),
            'extensions': [], 'version': 0}


def view(state, today):
    """Snapshots are immutable; projected dates slide, completed dates never do."""
    start = date.fromisoformat(state['startDate'])
    approved = sum(e.get('approvedDays', 0) for e in state['extensions'] if e['status'] == 'approved')
    backups = state['includedBackupDays']
    total = len(state['days'])
    # Plans may continue an ongoing journey (first uploaded day = 24 etc.); anchor
    # all date math on the first day number actually present, not on 1.
    first_day = state['days'][0]['day'] if state['days'] else 1
    deadline = start + timedelta(days=total + backups + approved - 1)
    rows, current, complete, done_tasks, mandatory_done = [], None, 0, 0, 0
    mandatory_total = sum(sum(bool(t["mandatory"]) for t in d["tasks"]) for d in state["days"])
    next_date = start
    projected_finish = start
    for day in state['days']:
        required = [t for t in day['tasks'] if t['mandatory']]
        is_done = all(t['id'] in day['completions'] for t in required)
        nominal = start + timedelta(days=day['day'] - first_day)
        scheduled = date.fromisoformat(day['scheduledDate']) if day.get('scheduledDate') else next_date
        actual = date.fromisoformat(day['completedOn']) if is_done else None
        projected = actual or max(next_date, today)
        if not is_done and current is None:
            current = day['day']
        done_tasks += len(day['completions'])
        mandatory_done += sum(t['id'] in day['completions'] for t in required)
        complete += int(is_done)
        tasks = [{**t, 'done': t['id'] in day['completions'],
                  'completion': day['completions'].get(t['id'])} for t in day['tasks']]
        rows.append({'day': day['day'], 'nominalDate': nominal.isoformat(),
                     'scheduledDate': scheduled.isoformat(), 'projectedDate': projected.isoformat(),
                     'completedOn': day.get('completedOn'), 'completedAt': day.get('completedAt'),
                     'done': is_done, 'taskCount': len(tasks),
                     'tasks': tasks if is_done or day['day'] == current else [],
                     'locked': not is_done and (day['day'] != current or scheduled > today)})
        projected_finish = projected
        next_date = projected + timedelta(days=1)
    delay = max(0, (projected_finish - (start + timedelta(days=total - 1))).days)
    needed = max(0, delay - backups - approved)
    active = next((r for r in rows if r['day'] == current), None)
    can_work = active is not None and not active['locked'] and needed == 0
    if active and needed:
        active['locked'] = True
    return {'planId': state['planId'], 'name': state['name'], 'studentId': state['studentId'],
            'startDate': state['startDate'], 'startedAt': state['startedAt'],
            'currentDay': current or total, 'totalDays': total, 'completedDays': complete,
            'completedTasks': done_tasks, 'totalTasks': sum(len(d['tasks']) for d in state['days']),
            'progressPercent': round(mandatory_done * 100 / mandatory_total, 1),
            'mandatoryTasksCompleted': mandatory_done, 'mandatoryTasksTotal': mandatory_total, 'complete': complete == total,
            'canWork': can_work, 'overdueDays': delay, 'extensionDaysNeeded': needed,
            'includedBackupDays': backups, 'backupDaysUsed': min(backups, delay),
            'backupDaysRemaining': max(0, backups-delay), 'approvedExtensionDays': approved,
            'extensionDaysUsed': min(approved, max(0, delay-backups)),
            'extensionDaysRemaining': max(0, approved-max(0, delay-backups)),
            'deadline': deadline.isoformat(), 'projectedFinishDate': projected_finish.isoformat(),
            'remainingCalendarDays': max(0, (deadline-today).days+1),
            'extensions': deepcopy(state['extensions']), 'days': rows,
            'version': state['version']}


def complete_task(state, task_id, today, now):
    out = deepcopy(state)
    for day in out['days']:
        if task_id in day['completions']:
            return out  # late network retries remain idempotent even after expiry
    status = view(state, today)
    if not status['canWork']:
        raise HTTPException(409, 'This day is locked. Finish the current day, wait for its IST date, or request an extension.')
    day = next((d for d in out['days'] if d['day'] == status['currentDay']), None)
    if day is None:
        raise HTTPException(409, 'The current day is not part of this plan.')
    if not any(t['id'] == task_id for t in day['tasks']):
        raise HTTPException(409, 'Only tasks from the current personal day can be completed.')
    scheduled = next(r for r in status['days'] if r['day'] == day['day'])['scheduledDate']
    day['scheduledDate'] = scheduled
    day['completions'][task_id] = {'completedAt': now, 'completedOn': today.isoformat(),
                                  'scheduledDate': scheduled, 'source': 'student-confirmed'}
    if all(t['id'] in day['completions'] for t in day['tasks'] if t['mandatory']):
        day['completedOn'], day['completedAt'] = today.isoformat(), now
    return out
