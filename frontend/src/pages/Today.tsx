import { useEffect, useState, useCallback } from 'react';
import type { DailyAgenda, GmailStatus, ScanRun, Task } from '../types';
import { getDailyAgenda, getGmailStatus, getMe, getScan, listTasks, syncGmail } from '../api/client';
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
        {agenda && agenda.timeline.length === 0 && (
          <div className="empty-state">
            Nothing urgent on the board. Sync Gmail to pull in the latest signal.
          </div>
        )}
        <div className="timeline">
          {visibleTimeline?.map((t) => (
            <button key={t.id} className="timeline-row" onClick={() => openTask(t.id)}>
              <span className="timeline-time">{fmtTime(fmtDeadline(t.deadline))}</span>
              <span className={`timeline-rail rail-${t.priority}`} aria-hidden="true" />
              <div className="timeline-body">
                <div className="timeline-top">
                  <span className="timeline-title">{t.title}</span>
                  {t.is_blocking && <span className="blocking-chip">blocks work</span>}
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
