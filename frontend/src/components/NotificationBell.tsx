import { useEffect, useRef, useState } from 'react';
import type { Notification } from '../types';
import { getNotifications, markNotificationsRead } from '../api/client';
import { shortDateTime } from '../format';

export default function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const load = () => getNotifications().then(setItems).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const unread = items.filter((n) => !n.is_read).length;
  const markRead = async () => {
    await markNotificationsRead();
    setItems((current) => current.map((n) => ({ ...n, is_read: true })));
  };

  return (
    <div className="bell" ref={ref}>
      <button className="btn btn-icon" aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} onClick={() => setOpen((v) => !v)}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4" /></svg>
        {unread > 0 && <span className="bell-count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="popover">
          <div className="popover-head"><strong>Notifications</strong>{unread > 0 && <button className="link" onClick={markRead}>Mark all read</button>}</div>
          {!items.length && <p className="muted">Nothing yet.</p>}
          {items.slice(0, 10).map((n) => (
            <div key={n.id} className={`notice${n.is_read ? '' : ' is-unread'}`}>
              <strong>{n.title}</strong>
              <p>{n.message}</p>
              <time>{shortDateTime(n.created_at)}</time>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
