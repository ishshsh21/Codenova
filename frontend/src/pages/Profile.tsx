import { useEffect, useState } from 'react';
import type { DataSummary, User } from '../types';
import { deleteAccount, deleteImportedData, disconnectGmail, getDataSummary, logout, updateProfile } from '../api/client';
import { useToast } from '../components/Toast';

const lines = (text: string) => text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);

export default function Profile({ user, onUserChange }: { user: User; onUserChange: (u: User) => void }) {
  const [classes, setClasses] = useState(user.my_classes.join('\n'));
  const [vip, setVip] = useState(user.vip_senders.join('\n'));
  const [ignored, setIgnored] = useState(user.ignored_senders.join('\n'));
  const [saving, setSaving] = useState(false);
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const { showToast } = useToast();

  useEffect(() => { getDataSummary().then(setSummary).catch(() => undefined); }, []);

  const dirty = classes !== user.my_classes.join('\n') || vip !== user.vip_senders.join('\n') || ignored !== user.ignored_senders.join('\n');

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await updateProfile({ my_classes: lines(classes), vip_senders: lines(vip), ignored_senders: lines(ignored) });
      onUserChange(updated);
      setClasses(updated.my_classes.join('\n'));
      showToast('Saved. Your tasks have been re-ranked.', 'success');
    } catch {
      showToast('Could not save. Try again.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const confirmThen = async (question: string, action: () => Promise<void>) => {
    if (!window.confirm(question)) return;
    try { await action(); } catch { showToast('That did not go through. Try again.', 'error'); }
  };

  return (
    <>
      <header className="page-head">
        <h1>Profile</h1>
        <p className="muted">{user.name} · {user.email}</p>
      </header>

      <form className="card" onSubmit={save}>
        <h2>Your classes</h2>
        <p className="muted">
          List the class, division or course codes you're actually in, one per line. For example <code>Class A</code>, <code>SY-B</code> or <code>CS201</code>.
          Mail addressed to a different class goes to FYI instead of your tasks, and mail for your class is ranked a little higher.
        </p>
        <textarea rows={3} aria-label="Your classes" placeholder="Class A" value={classes} onChange={(e) => setClasses(e.target.value)} />

        <h2>Senders</h2>
        <div className="two-col">
          <label>Always important
            <small className="muted">Their mail ranks higher. One email or domain per line.</small>
            <textarea rows={4} placeholder="hod@college.edu" value={vip} onChange={(e) => setVip(e.target.value)} />
          </label>
          <label>Never read
            <small className="muted">Skipped completely when scanning.</small>
            <textarea rows={4} placeholder="promo@shop.com" value={ignored} onChange={(e) => setIgnored(e.target.value)} />
          </label>
        </div>
        <div className="row-gap"><button className="btn btn-primary" disabled={!dirty || saving}>{saving ? 'Saving…' : 'Save'}</button></div>
      </form>

      <section className="card">
        <h2>Your data</h2>
        {summary && (
          <p className="muted">
            Stored: {summary.imported_emails} emails, {summary.tasks} tasks, {summary.scans} scans, {summary.notifications} notifications.
            Access: {summary.gmail_scopes.length ? 'read-only Gmail' : 'none'}.
          </p>
        )}
        <div className="row-gap">
          <button className="btn" onClick={() => logout().then(() => window.location.assign('/'))}>Sign out</button>
          <button className="btn btn-danger" onClick={() => confirmThen('Delete all imported emails, tasks and scans? Your account and Gmail connection stay.', async () => {
            await deleteImportedData();
            setSummary((s) => s && { ...s, imported_emails: 0, tasks: 0, scans: 0, notifications: 0 });
            showToast('Imported data deleted.', 'success');
          })}>Delete imported data</button>
          <button className="btn btn-danger" onClick={() => confirmThen('Disconnect Gmail and sign out?', async () => {
            await disconnectGmail(); await logout(); window.location.assign('/');
          })}>Disconnect Gmail</button>
          <button className="btn btn-danger" onClick={() => confirmThen('Permanently delete your account and everything in it?', async () => {
            await deleteAccount(); window.location.assign('/');
          })}>Delete account</button>
        </div>
      </section>
    </>
  );
}
