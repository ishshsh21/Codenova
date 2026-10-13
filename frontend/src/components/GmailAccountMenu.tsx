import { useState } from 'react';
import type { GmailAccount, GmailAccounts } from '../types';
import { addGmailAccount, getGmailAccounts, removeGmailAccount, renameGmailAccount, selectGmailAccount } from '../api/client';
import { useToast } from './Toast';
import { ACCOUNT_CHANGED_EVENT } from './gmailAccounts';

const LABEL_PRESETS = ['School', 'Personal', 'Work'];
const OTHER = '__other__';

function initial(account: GmailAccount) {
  return (account.label || account.email)[0]?.toUpperCase() ?? '?';
}

export default function GmailAccountMenu({
  data, setData, onClose,
}: { data: GmailAccounts | null; setData: (value: GmailAccounts) => void; onClose: () => void }) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [preset, setPreset] = useState(LABEL_PRESETS[0]);
  const [custom, setCustom] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState('');

  if (!data) return null;
  const many = data.accounts.length > 1;

  const select = async (accountId: string) => {
    if (accountId === data.selected) { onClose(); return; }
    setBusy(true);
    try {
      setData(await selectGmailAccount(accountId));
      window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT));
      onClose();
    } catch {
      showToast('Could not switch Gmail account.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const connect = async () => {
    const label = preset === OTHER ? custom.trim() : preset;
    setBusy(true);
    try {
      window.location.href = (await addGmailAccount(label)).authorization_url;
    } catch (err) {
      setBusy(false);
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      showToast(typeof detail === 'string' ? detail : 'Could not start Google sign-in.', 'error');
    }
  };

  const saveLabel = async (account: GmailAccount) => {
    setBusy(true);
    try {
      const updated = await renameGmailAccount(account.id, editLabel.trim());
      setData({ ...data, accounts: data.accounts.map((item) => (item.id === account.id ? updated : item)) });
      setEditingId(null);
    } catch {
      showToast('Could not rename this account.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (account: GmailAccount) => {
    if (!window.confirm(`Disconnect ${account.email}? Emails and tasks already imported from it are kept.`)) return;
    setBusy(true);
    try {
      await removeGmailAccount(account.id);
      setData(await getGmailAccounts());
      window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT));
      showToast(`${account.email} disconnected.`, 'info');
    } catch {
      showToast('Could not disconnect this account.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="account-menu-section">Gmail accounts</div>
      {many && (
        <button className="account-menu-account" role="menuitem" disabled={busy} onClick={() => select('all')}>
          <span className="user-avatar">∗</span>
          <span><strong>All accounts</strong><small>Show and search every connected account</small></span>
          {data.selected === 'all' && <b>✓</b>}
        </button>
      )}
      {data.accounts.map((account) => (
        editingId === account.id ? (
          <div className="account-form" key={account.id}>
            <label>
              Label for {account.email}
              <input
                autoFocus
                maxLength={30}
                value={editLabel}
                placeholder="School, Personal, Work…"
                onChange={(event) => setEditLabel(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') saveLabel(account); }}
              />
            </label>
            <div className="account-form-actions">
              <button className="btn-primary" disabled={busy} onClick={() => saveLabel(account)}>Save</button>
              <button className="btn-ghost" onClick={() => setEditingId(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="account-menu-row" key={account.id}>
            <button className="account-menu-account" role="menuitem" disabled={busy} onClick={() => select(account.id)}>
              <span className="user-avatar">{initial(account)}</span>
              <span>
                <strong>{account.label || account.email}{account.is_primary && many && <span className="account-label-chip">sign-in</span>}</strong>
                <small>{account.label ? account.email : 'No label yet'}</small>
              </span>
              {(data.selected === account.id || (!many && data.selected === 'all')) && <b>✓</b>}
            </button>
            <button className="account-menu-tool" title="Edit label" aria-label={`Edit label for ${account.email}`} onClick={() => { setEditingId(account.id); setEditLabel(account.label); }}>✎</button>
            {many && <button className="account-menu-tool" title="Disconnect account" aria-label={`Disconnect ${account.email}`} disabled={busy} onClick={() => remove(account)}>×</button>}
          </div>
        )
      ))}
      {adding ? (
        <div className="account-form">
          <label>
            Label
            <select value={preset} onChange={(event) => setPreset(event.target.value)}>
              {LABEL_PRESETS.map((name) => <option key={name} value={name}>{name}</option>)}
              <option value={OTHER}>Other…</option>
            </select>
          </label>
          {preset === OTHER && (
            <label>
              Custom label
              <input maxLength={30} value={custom} placeholder="e.g. Club" onChange={(event) => setCustom(event.target.value)} />
            </label>
          )}
          <p className="account-form-note">You'll sign in with Google and grant read-only Gmail access for this account only.</p>
          <div className="account-form-actions">
            <button className="btn-primary" disabled={busy} onClick={connect}>{busy ? 'Opening Google…' : 'Continue with Google'}</button>
            <button className="btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button className="account-menu-add" role="menuitem" onClick={() => setAdding(true)}>+ Add Gmail account</button>
      )}
    </>
  );
}
