import { useEffect, useState } from 'react';
import type { DataSummary, User } from '../types';
import { deleteImportedData, disconnectGmail, getDataSummary, getMe, logout, updateSettings } from '../api/client';
import { useToast } from '../components/Toast';

export default function Settings() {
  const [user, setUser] = useState<User | null>(null);
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { showToast } = useToast();

  useEffect(() => {
    Promise.all([getMe(), getDataSummary()]).then(([me, data]) => { setUser(me); setSummary(data); }).catch(() => setError('Could not load settings.')).finally(() => setSaved(false));
  }, []);

  if (!user || !summary) return <div className="loading-state">Loading your settings…</div>;

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaving(true); setError(null);
    try { setUser(await updateSettings(user)); setSaved(true); showToast('Settings saved.', 'success'); }
    catch { setError('Could not save settings.'); }
    finally { setSaving(false); }
  };

  const clearData = async () => {
    if (!window.confirm('Delete imported emails, tasks, scan history, and notifications? Your Gmail connection will remain.')) return;
    try { await deleteImportedData(); setSummary({ ...summary, imported_emails: 0, tasks: 0, scans: 0, notifications: 0 }); showToast('Imported data deleted.', 'success'); }
    catch { showToast('Could not delete imported data.', 'error'); }
  };

  const reconnectGmail = async () => {
    if (!window.confirm('Disconnect Gmail now? You will be signed out and can reconnect with a fresh Google consent grant.')) return;
    try {
      await disconnectGmail();
      await logout();
      window.location.assign('/login');
    } catch {
      showToast('Could not disconnect Gmail.', 'error');
    }
  };

  return <div className="page settings-page">
    <div className="page-header"><div><h1>Settings</h1><p className="page-sub">Tune how Signal reads and organizes your workday.</p></div></div>
    {error && <div className="sync-error-banner">{error}</div>}
    <form className="settings-card" onSubmit={save}>
      <span className="section-title">Workday preferences</span>
      <div className="settings-grid">
        <label>Timezone<input value={user.timezone} onChange={(e) => setUser({ ...user, timezone: e.target.value })} /></label>
        <label>Default scan days<input type="number" min="1" max="365" value={user.default_scan_days} onChange={(e) => setUser({ ...user, default_scan_days: Number(e.target.value) })} /></label>
        <label>Workday starts<input type="time" value={user.workday_start} onChange={(e) => setUser({ ...user, workday_start: e.target.value })} /></label>
        <label>Workday ends<input type="time" value={user.workday_end} onChange={(e) => setUser({ ...user, workday_end: e.target.value })} /></label>
      </div>
      <label className="settings-check"><input type="checkbox" checked={user.notify_scan_completion} onChange={(e) => setUser({ ...user, notify_scan_completion: e.target.checked })} /> Notify me when scans complete</label>
      <div className="settings-two-column"><label>VIP senders<textarea placeholder="One email or domain per line" value={(user.vip_senders || []).join('\n')} onChange={(e) => setUser({ ...user, vip_senders: e.target.value.split('\n').filter(Boolean) })} /></label><label>Ignored senders<textarea placeholder="One email or domain per line" value={(user.ignored_senders || []).join('\n')} onChange={(e) => setUser({ ...user, ignored_senders: e.target.value.split('\n').filter(Boolean) })} /></label></div>
      <div className="settings-actions"><button className="btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</button>{saved && <span className="saved-note">Saved</span>}</div>
    </form>
    <section className="settings-card privacy-card"><span className="section-title">Privacy dashboard</span><div className="privacy-metrics"><strong>{summary.imported_emails}<small>imported emails</small></strong><strong>{summary.tasks}<small>tasks</small></strong><strong>{summary.scans}<small>scans</small></strong><strong>{summary.notifications}<small>notifications</small></strong></div><p>Active Gmail scopes: {summary.gmail_scopes.join(', ') || 'none'}</p><div className="settings-actions"><button className="btn-danger" onClick={clearData}>Delete imported data</button><button className="btn-danger" onClick={reconnectGmail}>Disconnect Gmail</button></div></section>
  </div>;
}
