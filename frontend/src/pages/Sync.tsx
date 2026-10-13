import { useCallback, useEffect, useState } from 'react';
import type { GmailStatus, ScanRange, ScanRun, User } from '../types';
import { deleteScan, errorMessage, getGmailStatus, getScan, getScans, rerunScan, startScan, updateProfile } from '../api/client';
import { shortDate, shortDateTime } from '../format';
import { useToast } from '../components/Toast';

const STAGES: Record<string, string> = {
  QUEUED: 'Waiting to start',
  FETCHING_EMAILS: 'Reading your inbox',
  PROCESSING_EMAILS: 'Sorting tasks from FYI',
  BUILDING_AGENDA: 'Ranking your tasks',
};
const today = () => new Date().toISOString().slice(0, 10);
const isRunning = (s: ScanRun) => s.status === 'QUEUED' || s.status === 'RUNNING';

export default function Sync({ user, onUserChange }: { user: User; onUserChange: (u: User) => void }) {
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [scans, setScans] = useState<ScanRun[]>([]);
  const [range, setRange] = useState<ScanRange>({});
  const [error, setError] = useState<string | null>(null);
  const { showToast } = useToast();

  const load = useCallback(async () => {
    const [s, list] = await Promise.all([getGmailStatus(), getScans()]);
    setStatus(s);
    setScans(list);
  }, []);
  useEffect(() => { load(); }, [load]);

  const active = scans.find(isRunning) ?? null;

  // Poll only while a scan is running; the bell reports the result if the user leaves this page.
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(async () => {
      try {
        const scan = await getScan(active.id);
        setScans((list) => list.map((s) => (s.id === scan.id ? scan : s)));
        if (!isRunning(scan)) {
          if (scan.status === 'COMPLETED') showToast(`Scan finished: ${scan.tasks_created} new task${scan.tasks_created === 1 ? '' : 's'}.`, 'success');
          else showToast('Scan failed. See the details below.', 'error');
          load();
        }
      } catch { /* keep polling through brief network blips */ }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [active, load, showToast]);

  const begin = async (start: () => Promise<unknown>) => {
    setError(null);
    try {
      await start();
      await load();
    } catch (err) {
      setError(errorMessage(err, 'Could not start the scan. Is the backend running?'));
    }
  };

  const scanRange = () => {
    if (range.start_date && range.end_date && range.start_date > range.end_date) {
      setError('The start date has to be before the end date.');
      return;
    }
    begin(() => startScan(range));
  };

  const saveDefaults = async (patch: Partial<User>) => {
    onUserChange(await updateProfile(patch));
    showToast('Saved.', 'success');
  };

  return (
    <>
      <header className="page-head">
        <h1>Sync</h1>
        <p className="muted">
          {status?.connected ? <>Reading <strong>{status.google_account_email}</strong> (read-only)</> : 'Gmail is not connected.'}
          {status?.last_synced_at && <> · last synced {shortDateTime(status.last_synced_at)}</>}
        </p>
      </header>

      {error && <div className="banner banner-error">{error}</div>}

      <section className="card">
        <h2>Scan Gmail</h2>
        {active ? (
          <div className="progress">
            <div className="progress-label">
              <strong>{STAGES[active.stage] ?? 'Working'}</strong>
              <span className="muted">{active.progress_total ? `${active.progress} / ${active.progress_total}` : 'Starting…'}</span>
            </div>
            <div className="progress-track"><span style={{ width: `${active.progress_total ? Math.max(4, (active.progress / active.progress_total) * 100) : 4}%` }} /></div>
            <p className="muted">You can leave this page. The bell will tell you when it's done.</p>
          </div>
        ) : (
          <div className="scan-controls">
            <button className="btn btn-primary" onClick={() => begin(() => startScan())}>Scan the last {user.default_scan_days} days</button>
            <span className="muted">or pick dates</span>
            <label>From<input type="date" max={range.end_date || today()} value={range.start_date ?? ''} onChange={(e) => setRange({ ...range, start_date: e.target.value || undefined })} /></label>
            <label>To<input type="date" min={range.start_date} max={today()} value={range.end_date ?? ''} onChange={(e) => setRange({ ...range, end_date: e.target.value || undefined })} /></label>
            <button className="btn" disabled={!range.start_date && !range.end_date} onClick={scanRange}>Scan these dates</button>
          </div>
        )}
        <div className="defaults">
          <label>Default window (days)
            <input type="number" min={1} max={365} defaultValue={user.default_scan_days}
              onBlur={(e) => { const v = Number(e.target.value); if (v >= 1 && v <= 365 && v !== user.default_scan_days) saveDefaults({ default_scan_days: v }); }} />
          </label>
          <label className="check">
            <input type="checkbox" checked={user.notify_scan_completion} onChange={(e) => saveDefaults({ notify_scan_completion: e.target.checked })} />
            Notify me when a scan finishes
          </label>
        </div>
      </section>

      <section className="group">
        <header className="group-head"><h2>Past scans</h2></header>
        {!scans.length && <p className="muted">No scans yet.</p>}
        <div className="stack">
          {scans.map((s) => (
            <article key={s.id} className={`scan scan-${s.status}`}>
              <div>
                <strong>{s.start_date ? `${shortDate(s.start_date)} – ${shortDate(s.end_date) || 'now'}` : `Up to ${shortDate(s.end_date)}`}</strong>
                <p className="muted">
                  {s.status === 'COMPLETED' && `${s.messages_fetched} emails · ${s.tasks_created} new tasks · ${(s.duration_ms / 1000).toFixed(1)}s`}
                  {s.status === 'FAILED' && (s.error_message || 'Failed')}
                  {isRunning(s) && 'Running…'}
                </p>
              </div>
              <time className="muted">{shortDateTime(s.created_at)}</time>
              <div className="row-gap">
                <button className="btn btn-quiet" disabled={Boolean(active)} onClick={() => begin(() => rerunScan(s.id))}>Run again</button>
                <button className="btn btn-quiet" disabled={isRunning(s)} onClick={async () => { await deleteScan(s.id); load(); }}>Remove</button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
