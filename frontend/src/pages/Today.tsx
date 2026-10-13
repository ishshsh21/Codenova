import { useEffect, useState, useCallback, useRef } from 'react';
import type { CalendarEvent, CalendarStatus, DailyAgenda, GmailStatus, ScanRun, Task } from '../types';
import {
  connectCalendar, disconnectCalendar, getCalendarStatus, getDailyAgenda, getGmailStatus, getMe, getScan, listTasks, syncCalendar, syncGmail,
} from '../api/client';
import StatCard from '../components/StatCard';
import PriorityBadge from '../components/PriorityBadge';
import TaskDetailPanel from '../components/TaskDetailPanel';
import DateRangePicker, { type DateRange } from '../components/DateRangePicker';
import { useToast } from '../components/Toast';

type KpiFilter = 'ALL' | 'CRITICAL' | 'DUE_TODAY' | 'OVERDUE' | 'THIS_WEEK' | 'NO_ACTION';

function fmtTime(t?: string | null) {
  return t ?? '—';
}

function fmtDeadline(iso?: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function fmtClock(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

// The API returns UTC timestamps without a zone suffix.
function fmtSyncedAt(iso?: string | null) {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export default function Today({ workspaceOnly = false }: { workspaceOnly?: boolean }) {
  const [agenda, setAgenda] = useState<DailyAgenda | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [defaultScanDays, setDefaultScanDays] = useState(30);
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeScanId, setActiveScanId] = useState<string | null>(null);
  const [activeScan, setActiveScan] = useState<ScanRun | null>(null);
  const [taskFilter, setTaskFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [kpiFilter, setKpiFilter] = useState<KpiFilter>('ALL');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [focusTaskId, setFocusTaskId] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<ScanRun | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  // Google Calendar sync is part of the Today page only (workspaceOnly); Overview never uses it.
  const [calStatus, setCalStatus] = useState<CalendarStatus | null>(null);
  const [calEvents, setCalEvents] = useState<CalendarEvent[]>([]);
  const [calBusy, setCalBusy] = useState(false);
  const calSyncing = useRef(false);
  const { showToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, s, openTasks, user] = await Promise.all([getDailyAgenda(), getGmailStatus(), listTasks({ status: 'OPEN' }), getMe()]);
      setAgenda(a);
      setStatus(s);
      setTasks(openTasks);
      setDefaultScanDays(user.default_scan_days);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runCalendarSync = useCallback(async (announce = false) => {
    if (calSyncing.current) return;
    calSyncing.current = true;
    try {
      const result = await syncCalendar();
      setCalEvents(result.events);
      setCalStatus(await getCalendarStatus());
      if (result.changed) await load();
      if (result.conflicts.length) {
        showToast(`${result.conflicts.length} synced task${result.conflicts.length === 1 ? ' overlaps' : 's overlap'} an existing calendar event.`, 'info');
      }
      if (announce) {
        if (result.error) showToast(result.error, 'error');
        else showToast(result.changed ? 'Calendar synced.' : 'Calendar is up to date.', 'success');
      }
    } catch {
      if (announce) showToast('Could not sync Google Calendar.', 'error');
    } finally {
      calSyncing.current = false;
    }
  }, [load, showToast]);

  useEffect(() => {
    if (!workspaceOnly) return;
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get('calendar');
    if (!outcome) return;
    params.delete('calendar');
    window.history.replaceState({}, '', window.location.pathname + (params.toString() ? `?${params}` : ''));
    if (outcome === 'connected') showToast('Google Calendar connected.', 'success');
    else if (outcome === 'denied') showToast('Google Calendar was not connected: calendar access is needed to sync.', 'error');
    else showToast('Could not connect Google Calendar. Please try again.', 'error');
  }, [workspaceOnly, showToast]);

  useEffect(() => {
    if (!workspaceOnly) return;
    let cancelled = false;
    getCalendarStatus().then((status) => {
      if (cancelled) return;
      setCalStatus(status);
      if (status.connected && !status.needs_reauth) void runCalendarSync();
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [workspaceOnly, runCalendarSync]);

  const calendarLive = workspaceOnly && Boolean(calStatus?.connected) && !calStatus?.needs_reauth;
  useEffect(() => {
    if (!calendarLive) return;
    const refresh = () => { if (document.visibilityState === 'visible') void runCalendarSync(); };
    const timer = window.setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('calendar-changed', refresh); // fired by the AI assistant after it edits the calendar
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('calendar-changed', refresh);
    };
  }, [calendarLive, runCalendarSync]);

  // A finished Gmail scan may have created tasks that should reach the calendar.
  const lastScanId = lastSync?.id;
  useEffect(() => { if (calendarLive && lastScanId) void runCalendarSync(); }, [calendarLive, lastScanId, runCalendarSync]);

  const handleConnectCalendar = async () => {
    setCalBusy(true);
    try {
      window.location.href = (await connectCalendar()).authorization_url;
    } catch (err) {
      setCalBusy(false);
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      showToast(detail || 'Could not start Google Calendar sign-in.', 'error');
    }
  };

  const handleDisconnectCalendar = async () => {
    if (!window.confirm('Disconnect Google Calendar? Events already in Google Calendar stay there; Today stops syncing.')) return;
    try {
      await disconnectCalendar();
      setCalStatus({ connected: false, needs_reauth: false });
      setCalEvents([]);
      await load();
      showToast('Google Calendar disconnected.', 'info');
    } catch {
      showToast('Could not disconnect Google Calendar.', 'error');
    }
  };

  const handleCalendarSyncNow = async () => {
    setCalBusy(true);
    await runCalendarSync(true);
    setCalBusy(false);
  };

  useEffect(() => {
    if (!activeScanId) return;
    const timer = window.setInterval(async () => {
      try {
        const scan = await getScan(activeScanId);
        setActiveScan(scan);
        if (scan.status === 'COMPLETED' || scan.status === 'FAILED') {
          window.clearInterval(timer);
          setActiveScanId(null);
          setLastSync(scan);
          if (scan.status === 'COMPLETED') {
            showToast(`Scan completed: ${scan.messages_fetched} emails scanned.`, 'success');
            await load();
          } else {
            setSyncError(scan.error_message || 'Scan failed. Check the backend logs and try again.');
            showToast('Scan failed. Check the scan history for details.', 'error');
          }
        }
      } catch {
        // Keep polling: a temporary request failure should not lose scan tracking.
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeScanId, load, showToast]);

  const handleSync = async (range: DateRange) => {
    setSyncError(null);
    try {
      const scan = await syncGmail(range);
      setActiveScanId(scan.id);
      setActiveScan({ ...scan, stage: 'QUEUED', progress: 0, progress_total: 0, messages_fetched: 0, messages_processed: 0, tasks_created: 0, tasks_updated: 0, duration_ms: 0 });
      showToast('Scan started. You can keep using the app while it runs.', 'info');
    } catch (err) {
      const message = (err as { response?: { data?: { detail?: string | { msg: string }[] } } })?.response?.data?.detail;
      setSyncError(
        typeof message === 'string' ? message : Array.isArray(message) ? message[0]?.msg : 'Sync failed — check the backend is running and Gmail is connected.'
      );
    }
  };

  const selectKpiFilter = (filter: KpiFilter) => {
    setKpiFilter((current) => current === filter ? 'ALL' : filter);
  };

  useEffect(() => {
    const filters: Record<string, KpiFilter> = { Actionable: 'ALL', Critical: 'CRITICAL', 'Due today': 'DUE_TODAY', Overdue: 'OVERDUE', 'This week': 'THIS_WEEK', 'No action needed': 'NO_ACTION' };
    const onKpiFilter = (event: Event) => selectKpiFilter(filters[(event as CustomEvent<string>).detail]);
    window.addEventListener('kpi-filter', onKpiFilter);
    return () => window.removeEventListener('kpi-filter', onKpiFilter);
  }, []);

  const visibleTimeline = agenda ? tasks.filter((task) => {
    const matchesText = !taskFilter.trim() || task.title.toLowerCase().includes(taskFilter.toLowerCase());
    const matchesPriority = priorityFilter === 'ALL' || task.priority === priorityFilter;
    const isOverdue = agenda.task_ids.overdue.includes(task.id);
    const isDueToday = agenda.task_ids.due_today.includes(task.id);
    const isThisWeek = agenda.task_ids.this_week.includes(task.id);
    if (kpiFilter === 'THIS_WEEK' && !isThisWeek) return false;
    const matchesKpi = kpiFilter === 'ALL' || (kpiFilter === 'CRITICAL' && task.priority === 'P0') || (kpiFilter === 'DUE_TODAY' && isDueToday) || (kpiFilter === 'OVERDUE' && isOverdue) || (kpiFilter === 'THIS_WEEK' && isThisWeek) || (kpiFilter === 'NO_ACTION' && false);
    return matchesText && matchesPriority && matchesKpi;
  }) : [];
  const visibleEvents = workspaceOnly && priorityFilter === 'ALL' && kpiFilter === 'ALL'
    ? calEvents.filter((event) => !taskFilter.trim() || event.title.toLowerCase().includes(taskFilter.toLowerCase()))
    : [];
  const focusTasks = agenda?.timeline.slice(0, 3) ?? [];
  const nextUpTask = agenda?.timeline[0] ?? null;
  // "Next Up" is the first scheduled item. By default, "Focus" should show
  // the next distinct item; it changes to a user-selected task when one is
  // opened from the timeline.
  const focusTask = agenda?.timeline.find((task) => task.id === focusTaskId)
    ?? agenda?.timeline.find((task) => task.id !== nextUpTask?.id)
    ?? null;
  const openTask = (taskId: string) => { setFocusTaskId(taskId); setSelectedTaskId(taskId); };

  if (loading && !agenda) {
    return <div className="loading-state">Reading the signal off your inbox…</div>;
  }

  return (
    <div className={`page overview-page${workspaceOnly ? ' today-workspace' : ''}`}>
      <div className="page-header">
        <div>
          <h1>Today's Timeline</h1>
          <p className="page-sub">
            {agenda?.date && new Date(agenda.date).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}
            {status?.last_synced_at && (
              <> · last synced {new Date(status.last_synced_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</>
            )}
          </p>
        </div>
        <DateRangePicker onSync={handleSync} busy={Boolean(activeScanId)} defaultScanDays={defaultScanDays} />
      </div>

      {syncError && <div className="sync-error-banner">{syncError}</div>}

      {workspaceOnly && calStatus && (
        <div className="calendar-sync-bar">
          <div className="calendar-sync-info">
            <strong>Google Calendar</strong>
            {!calStatus.connected && <span>Sync today's tasks and events with Google Calendar, both ways.</span>}
            {calStatus.connected && !calStatus.needs_reauth && (
              <span>Synced with {calStatus.google_account_email}{fmtSyncedAt(calStatus.last_synced_at) && <> · {fmtSyncedAt(calStatus.last_synced_at)}</>}</span>
            )}
            {calStatus.connected && calStatus.needs_reauth && <span className="calendar-sync-warn">Access expired or was revoked. Reconnect to resume syncing.</span>}
          </div>
          <div className="calendar-sync-actions">
            {(!calStatus.connected || calStatus.needs_reauth) ? (
              <button className="btn-primary" onClick={handleConnectCalendar} disabled={calBusy}>
                {calBusy ? 'Opening Google…' : calStatus.needs_reauth ? 'Reconnect Calendar' : 'Connect Calendar'}
              </button>
            ) : (
              <>
                <button className="btn-secondary" onClick={handleCalendarSyncNow} disabled={calBusy}>{calBusy ? 'Syncing…' : 'Sync now'}</button>
                <button className="btn-ghost" onClick={handleDisconnectCalendar}>Disconnect</button>
              </>
            )}
          </div>
        </div>
      )}

      {activeScan && activeScanId && (
        <div className="scan-progress-card">
          <div className="scan-progress-heading">
            <strong>{activeScan.stage === 'FETCHING_EMAILS' ? 'Reading your inbox' : activeScan.stage === 'PROCESSING_EMAILS' ? 'Finding actionable work' : 'Building your agenda'}</strong>
            <span>{activeScan.progress_total ? `${activeScan.progress} / ${activeScan.progress_total}` : 'Starting…'}</span>
          </div>
          <div className="progress-track"><span style={{ width: `${activeScan.progress_total ? Math.max(5, (activeScan.progress / activeScan.progress_total) * 100) : 5}%` }} /></div>
          <p>Scan is running in the background. You can continue using Workday Signal.</p>
        </div>
      )}

      {lastSync && (
        <p className="sync-summary">
          Last scan: {lastSync.messages_fetched} emails
          {lastSync.start_date && lastSync.end_date && (
            <> from {new Date(lastSync.start_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            {' '}to {new Date(lastSync.end_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</>
          )}
          {!lastSync.start_date && !lastSync.end_date && <> (default: last 30 days)</>}
          {' '}· {lastSync.tasks_created} new task{lastSync.tasks_created === 1 ? '' : 's'}
        </p>
      )}

      {!workspaceOnly && agenda && (
        <div className="stat-grid">
          <StatCard label="Actionable" value={agenda.summary.actionable} />
          <StatCard label="Critical" value={agenda.summary.critical} tone="critical" />
          <StatCard label="Due today" value={agenda.summary.due_today} />
          <StatCard label="Overdue" value={agenda.summary.overdue} tone="critical" />
          <StatCard label="This week" value={agenda.summary.this_week} />
          <StatCard label="No action needed" value={agenda.no_action_count} tone="muted" />
        </div>
      )}

      {!workspaceOnly && agenda && agenda.timeline.length > 0 && (
        <div className="focus-grid focus-grid-single">
          <div className="focus-card"><span className="section-title">Focus next</span><div className="focus-list">{focusTasks.map((task, index) => <button className="focus-item" key={task.id} onClick={() => setSelectedTaskId(task.id)}><span>{String(index + 1).padStart(2, '0')}</span><strong>{task.title}</strong></button>)}</div></div>
        </div>
      )}

      {workspaceOnly && <div className="today-workspace-grid">
        <section className="today-workspace-card">
          <span className="section-title">Next Up</span>
          {nextUpTask ? <button className="today-workspace-task" onClick={() => openTask(nextUpTask.id)}><span className={`timeline-rail rail-${nextUpTask.priority}`} /><span><strong>{nextUpTask.title}</strong><small><PriorityBadge priority={nextUpTask.priority} /> <em>{fmtDeadline(nextUpTask.deadline) ?? 'No due time'}</em></small></span></button> : <p className="today-workspace-empty">No upcoming tasks.</p>}
        </section>
        <section className="today-workspace-card">
          <span className="section-title">Focus</span>
          {focusTask ? <button className="today-workspace-task" onClick={() => openTask(focusTask.id)}><span className={`timeline-rail rail-${focusTask.priority}`} /><span><strong>{focusTask.title}</strong><small><PriorityBadge priority={focusTask.priority} /> <em>Open</em></small></span></button> : <p className="today-workspace-empty">Select a task to focus on it.</p>}
        </section>
      </div>}

      <div className="timeline-section">
        <span className="section-title">Timeline</span>
        <div className="task-filters">
          <input aria-label="Search tasks" placeholder="Search tasks…" value={taskFilter} onChange={(e) => setTaskFilter(e.target.value)} />
          <select aria-label="Filter by priority" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
            <option value="ALL">All priorities</option><option value="P0">P0 critical</option><option value="P1">P1 high</option><option value="P2">P2 medium</option><option value="P3">P3 low</option><option value="P4">P4 info</option>
          </select>
        </div>
        {agenda && agenda.timeline.length === 0 && visibleEvents.length === 0 && (
          <div className="empty-state">
            Nothing urgent on the board. Sync Gmail to pull in the latest signal.
          </div>
        )}
        <div className="timeline">
          {visibleEvents.map((event) => (
            <a
              key={`event-${event.id}`}
              className="timeline-row calendar-event-row"
              href={event.html_link || undefined}
              target="_blank"
              rel="noopener noreferrer"
              title="Open in Google Calendar"
            >
              <span className="timeline-time">{event.all_day ? 'All day' : fmtClock(event.start)}</span>
              <span className="timeline-rail rail-EVENT" aria-hidden="true" />
              <div className="timeline-body">
                <div className="timeline-top">
                  <span className="timeline-title">{event.title}</span>
                  <span className="calendar-chip">Calendar</span>
                </div>
                <div className="timeline-bottom">
                  <span className="timeline-reason">
                    {event.all_day ? 'All-day event' : `${fmtClock(event.start)} – ${fmtClock(event.end)}`}{event.location ? ` · ${event.location}` : ''}
                  </span>
                </div>
              </div>
              <span className="timeline-deadline">{event.all_day ? '—' : fmtClock(event.end)}</span>
            </a>
          ))}
          {visibleTimeline?.map((t) => (
            <button key={t.id} className="timeline-row" onClick={() => openTask(t.id)}>
              <span className="timeline-time">{fmtTime(fmtDeadline(t.deadline))}</span>
              <span className={`timeline-rail rail-${t.priority}`} aria-hidden="true" />
              <div className="timeline-body">
                <div className="timeline-top">
                  <span className="timeline-title">{t.title}</span>
                  {t.is_blocking && <span className="blocking-chip">blocks work</span>}
                  {workspaceOnly && t.calendar_synced && <span className="calendar-chip" title="Synced with Google Calendar">Synced</span>}
                </div>
                <div className="timeline-bottom">
                  <PriorityBadge priority={t.priority} />
                  <span className="timeline-reason">{t.priority_reasons[0] ?? 'Open task'}</span>
                  {workspaceOnly && <span className="today-task-status">Open</span>}
                </div>
              </div>
              <span className="timeline-deadline">{fmtDeadline(t.deadline) ?? '—'}</span>
            </button>
          ))}
        </div>
        {agenda && agenda.timeline.length > 0 && !visibleTimeline?.length && <div className="empty-state">No tasks match these filters.</div>}
      </div>

      {selectedTaskId && (
        <TaskDetailPanel
          taskId={selectedTaskId}
          onClose={() => setSelectedTaskId(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}
