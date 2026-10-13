import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import type { User } from '../types';
import { logout } from '../api/client';
import NotificationCenter from './NotificationCenter';
import AIAssistant from './AIAssistant';
import GmailAccountMenu from './GmailAccountMenu';
import { ACCOUNT_CHANGED_EVENT, selectedAccountName, useGmailAccounts } from './gmailAccounts';
import { useToast } from './Toast';

type IconName = 'signal' | 'overview' | 'today' | 'week' | 'scan' | 'insights' | 'settings' | 'sparkle';

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    signal: <path d="M2 12h3l2.1-7 3.2 14L13 8l2 7 2-3h5" />,
    overview: <><path d="M3 10.5 12 3l9 7.5v8.25a1.25 1.25 0 0 1-1.25 1.25H4.25A1.25 1.25 0 0 1 3 18.75z" /><path d="M9 20v-6h6v6" /></>,
    today: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4m10-4v4M3 10h18m-10 4h4" /></>,
    week: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4m10-4v4M3 10h18M8 14h3m2 0h3m-8 3h3" /></>,
    scan: <><path d="M12 3a9 9 0 1 0 8.6 11.7" /><path d="M12 7v5l3 2m3-9v5h-5" /></>,
    insights: <><path d="M5 20V10m5 10V4m5 16v-7m5 7V7" /><rect x="3" y="7" width="4" height="4" rx="1" /><rect x="8" y="2" width="4" height="4" rx="1" /><rect x="13" y="10" width="4" height="4" rx="1" /><rect x="18" y="4" width="4" height="4" rx="1" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06-2.12 2.12-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V20h-3v-.08a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06-2.12-2.12.06-.06A1.65 1.65 0 0 0 7.2 15a1.65 1.65 0 0 0-1.51-1H5.6v-3h.08a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82L6.8 8.1 8.92 6l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V4.8h3v.08a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33L17.7 6l2.12 2.12-.06.06A1.65 1.65 0 0 0 19.43 10v.01a1.65 1.65 0 0 0 1.51 1h.08v3h-.08a1.65 1.65 0 0 0-1.54 1z" /></>,
    sparkle: <path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9zm7 14 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" />,
  };
  return <svg className={`icon icon-${name}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function SidebarLink({ to, icon, children, end = false, forceInactive = false }: { to: string; icon: IconName; children: React.ReactNode; end?: boolean; forceInactive?: boolean }) {
  return <NavLink to={to} end={end} className={({ isActive }) => `side-nav-link${isActive && !forceInactive ? ' active' : ''}`}><Icon name={icon} /><span>{children}</span></NavLink>;
}

export default function Shell({ user, children }: { user: User | null; children: React.ReactNode }) {
  const navigate = useNavigate(); const [assistantOpen, setAssistantOpen] = useState(false); const [accountMenuOpen, setAccountMenuOpen] = useState(false); const accountMenuRef = useRef<HTMLDivElement>(null);
  const handleLogout = async () => { await logout(); navigate('/login'); };
  const { data: accounts, setData: setAccounts, refresh: refreshAccounts } = useGmailAccounts(); const { showToast } = useToast();
  useEffect(() => {
    // Coming back from Google after "Add Gmail account".
    const params = new URLSearchParams(window.location.search); const outcome = params.get('gmail_account');
    if (!outcome) return;
    params.delete('gmail_account'); window.history.replaceState({}, '', window.location.pathname + (params.toString() ? `?${params}` : ''));
    if (outcome === 'added') showToast('Gmail account connected. Use “Sync Gmail” to scan it.', 'success');
    else if (outcome === 'updated') showToast('Gmail account reconnected.', 'success');
    else if (outcome === 'denied') showToast('Gmail account was not connected: read-only Gmail access is required.', 'error');
    else showToast('Could not connect that Gmail account. Please try again.', 'error');
    refreshAccounts(); window.dispatchEvent(new Event(ACCOUNT_CHANGED_EVENT));
  }, [showToast, refreshAccounts]);
  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => { if (accountMenuRef.current && !accountMenuRef.current.contains(event.target as Node)) setAccountMenuOpen(false); };
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setAccountMenuOpen(false); };
    document.addEventListener('mousedown', closeOnOutsideClick); document.addEventListener('keydown', closeOnEscape);
    return () => { document.removeEventListener('mousedown', closeOnOutsideClick); document.removeEventListener('keydown', closeOnEscape); };
  }, []);
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><Icon name="signal" /></span><div className="brand-text"><span className="brand-name">Workday Signal</span><span className="brand-sub">Gmail AI Workday Agent</span></div></div>
      <nav className="side-nav" aria-label="Primary navigation">
        <SidebarLink to="/" end icon="overview">Overview</SidebarLink><SidebarLink to="/today" icon="today">Today</SidebarLink><SidebarLink to="/week" icon="week">This Week</SidebarLink><SidebarLink to="/scans" icon="scan">Scan History</SidebarLink>
        <span className="side-nav-link is-disabled"><Icon name="insights" /><span>Insights</span></span><div className="side-nav-divider" /><SidebarLink to="/settings" icon="settings">Settings</SidebarLink>
      </nav>
      <div className="sidebar-bottom"><section className="assistant-card"><button className="assistant-launch" onClick={() => setAssistantOpen(true)}><div className="assistant-heading"><span className="assistant-icon"><Icon name="sparkle" /></span><div><strong>AI Assistant</strong><small><i /> Online</small></div></div><span className="assistant-prompt">Ask about your workday... <b>→</b></span></button></section>{user && <button className="sidebar-profile" title="Sign out" onClick={handleLogout}><span className="user-avatar">{user.name?.[0] ?? 'U'}</span><span className="user-meta"><strong>{user.name}</strong><small>{user.email}</small></span><span className="profile-chevron">⌄</span></button>}</div>
    </aside>
    <section className="main-shell"><header className="main-topbar"><div className="topbar-user">{user && <><NotificationCenter /><span className="topbar-divider" /><div className="account-menu" ref={accountMenuRef}><button className="account-menu-trigger" onClick={() => setAccountMenuOpen((open) => !open)} aria-expanded={accountMenuOpen} aria-haspopup="menu"><span className="user-avatar">{user.name?.[0] ?? 'U'}</span><span className="user-meta"><strong>{user.name}</strong><small>{selectedAccountName(accounts) ?? user.email}</small></span><span className="profile-chevron">⌄</span></button>{accountMenuOpen && <div className="account-menu-popover" role="menu">{accounts ? <GmailAccountMenu data={accounts} setData={setAccounts} onClose={() => setAccountMenuOpen(false)} /> : <button className="account-menu-account" role="menuitem" onClick={() => setAccountMenuOpen(false)}><span className="user-avatar">{user.name?.[0] ?? 'U'}</span><span><strong>{user.name}</strong><small>{user.email}</small></span><b>✓</b></button>}<div className="account-menu-divider" /><button className="account-menu-signout" role="menuitem" onClick={handleLogout}>Sign out</button></div>}</div></>}</div></header><main className="content">{children}</main></section><AIAssistant open={assistantOpen} onClose={() => setAssistantOpen(false)} />
  </div>;
}
