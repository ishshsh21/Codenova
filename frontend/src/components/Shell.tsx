import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import NotificationBell from './NotificationBell';
import Assistant from './Assistant';

const SECTIONS = [
  { to: '/', label: 'Now', end: true },
  { to: '/planner', label: 'Planner' },
  { to: '/fyi', label: 'FYI' },
  { to: '/sync', label: 'Sync' },
  { to: '/profile', label: 'Profile' },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const [assistantOpen, setAssistantOpen] = useState(false);
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand"><span className="brand-mark" aria-hidden="true">✦</span>Codenova</span>
        <nav className="tabs" aria-label="Sections">
          {SECTIONS.map((s) => (
            <NavLink key={s.to} to={s.to} end={s.end} className={({ isActive }) => `tab${isActive ? ' is-active' : ''}`}>
              {s.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-tools">
          <NotificationBell />
          <button className="btn btn-soft" onClick={() => setAssistantOpen(true)}>Ask</button>
        </div>
      </header>
      <main className="page">{children}</main>
      {assistantOpen && <Assistant onClose={() => setAssistantOpen(false)} />}
    </div>
  );
}
