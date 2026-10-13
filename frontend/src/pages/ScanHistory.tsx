import { useCallback, useEffect, useRef, useState } from 'react';
import type { Notification, ScanRun } from '../types';
import { deleteAccount, deleteScan, getNotifications, getScans, rerunScan } from '../api/client';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../components/Toast';

function formatDate(value?: string | null) {
  if (!value) return 'Default window';
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  });
}

function formatDateTime(value?: string | null) {
  if (!value) return '—';
  return new Date(value).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

export default function ScanHistory() {
  const [scans, setScans] = useState<ScanRun[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const { showToast } = useToast();
  const previousStatuses = useRef(new Map<string, string>());

  const load = useCallback(async () => {
    const [scanData, notificationData] = await Promise.all([getScans(), getNotifications()]);
    scanData.forEach((scan) => {
      const previous = previousStatuses.current.get(scan.id);
      if (previous && previous !== scan.status && scan.status === 'COMPLETED') {
        showToast('Scan completed.', 'success');
      } else if (previous && previous !== scan.status && scan.status === 'FAILED') {
        showToast('Scan failed. See the scan details for more information.', 'error');
      }
      previousStatuses.current.set(scan.id, scan.status);
    });
    setScans(scanData);
    setNotifications(notificationData);
  }, [showToast]);

  useEffect(() => {
    load()
      .catch(() => setError('Could not load scan history. Check that the backend is running.'))
      .finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    if (!scans.some((scan) => scan.status === 'QUEUED' || scan.status === 'RUNNING')) return;
    const timer = window.setInterval(() => load().catch(() => undefined), 1500);
    return () => window.clearInterval(timer);
  }, [scans, load]);

  const handleRerun = async (scan: ScanRun) => {
    try {
      const next = await rerunScan(scan.id);
      showToast('Scan started again as a new run.', 'info');
      previousStatuses.current.set(next.id, next.status);
      await load();
    } catch {
      showToast('Could not rerun this scan.', 'error');
    }
  };

  const handleDeleteScan = async (scan: ScanRun) => {
    if (!window.confirm('Delete this scan from your history? Gmail and tasks will be kept.')) return;
    try {
      await deleteScan(scan.id);
      setScans((current) => current.filter((item) => item.id !== scan.id));
      showToast('Scan deleted.', 'success');
    } catch {
      showToast('Could not delete this scan.', 'error');
    }
  };

  const handleDeleteAccount = async () => {
    const confirmed = window.confirm(
      'Delete your account and all Gmail data, tasks, scans, and notifications? This cannot be undone.'
    );
    if (!confirmed) return;
    try {
      await deleteAccount();
      navigate('/login', { replace: true });
    } catch {
      showToast('Could not delete the account.', 'error');
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Scan History</h1>
          <p className="page-sub">Every Gmail scan stays attached to your account.</p>
        </div>
      </div>

      {error && <div className="sync-error-banner">{error}</div>}
      {loading && <div className="loading-state">Loading your scans…</div>}
      {!loading && !scans.length && <div className="empty-state">No scans yet. Start one from Today.</div>}

      {!loading && scans.length > 0 && (
        <div className="scan-history-list">
          {scans.map((scan) => (
            <article className="scan-card" key={scan.id}>
              <div className="scan-card-top">
                <div>
                  <span className={`scan-status scan-status-${scan.status.toLowerCase()}`}>{scan.status}</span>
                  <h2>{formatDate(scan.start_date)}{scan.end_date ? ` → ${formatDate(scan.end_date)}` : ''}</h2>
                </div>
                <time>{formatDateTime(scan.created_at)}</time>
              </div>
              <p className="scan-query">{scan.gmail_query}</p>
              {(scan.status === 'QUEUED' || scan.status === 'RUNNING') && <div className="history-progress"><div className="progress-track"><span style={{ width: `${scan.progress_total ? Math.max(5, (scan.progress / scan.progress_total) * 100) : 5}%` }} /></div><span>{scan.stage.replaceAll('_', ' ').toLowerCase()} {scan.progress_total ? `· ${scan.progress}/${scan.progress_total}` : ''}</span></div>}
              {scan.status === 'COMPLETED' && (
                <div className="scan-metrics">
                  <span><strong>{scan.messages_fetched}</strong> emails</span>
                  <span><strong>{scan.messages_processed}</strong> processed</span>
                  <span><strong>{scan.tasks_created}</strong> new tasks</span>
                  <span><strong>{scan.tasks_updated}</strong> updated</span>
                  <span><strong>{scan.duration_ms}ms</strong> duration</span>
                </div>
              )}
              {scan.status === 'FAILED' && <p className="scan-failure">{scan.error_message || 'The scan failed.'}</p>}
              <div className="scan-actions">
                <button className="btn-secondary" onClick={() => handleRerun(scan)} disabled={scan.status === 'QUEUED' || scan.status === 'RUNNING'}>
                  Rerun scan
                </button>
                <button className="btn-ghost scan-delete" onClick={() => handleDeleteScan(scan)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      )}

      {notifications.length > 0 && (
        <section className="notification-history">
          <span className="section-title">Recent notifications</span>
          {notifications.slice(0, 20).map((notification) => (
            <div className="notification-row" key={notification.id}>
              <span className={`notification-dot notification-${notification.kind.toLowerCase()}`} />
              <div><strong>{notification.title}</strong><p>{notification.message}</p></div>
              <time>{formatDateTime(notification.created_at)}</time>
            </div>
          ))}
        </section>
      )}

      <section className="danger-zone">
        <span className="section-title">Account and data</span>
        <p>Delete your account, Gmail connection, imported emails, tasks, scan history, and notifications permanently.</p>
        <button className="btn-danger" onClick={handleDeleteAccount}>Delete account and all data</button>
      </section>
    </div>
  );
}
