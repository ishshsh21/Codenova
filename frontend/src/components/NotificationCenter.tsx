import { useEffect, useState } from 'react';
import type { Notification } from '../types';
import { getNotifications, markNotificationsRead } from '../api/client';

function timeLabel(value: string) {
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function NotificationCenter() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);

  const load = () => getNotifications().then(setItems).catch(() => undefined);
  useEffect(() => {
    load();
    const timer = window.setInterval(load, 10000);
    return () => window.clearInterval(timer);
  }, []);

  const unread = items.filter((item) => !item.is_read).length;
  const markRead = async () => {
    await markNotificationsRead();
    setItems((current) => current.map((item) => ({ ...item, is_read: true })));
  };

  return (
    <div className="notification-center">
      <button className="notification-trigger" onClick={() => setOpen((value) => !value)} aria-label="Notifications">
        ◌{unread > 0 && <span className="notification-count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && <div className="notification-popover">
        <div className="notification-popover-head"><strong>Notifications</strong>{unread > 0 && <button className="btn-ghost" onClick={markRead}>Mark read</button>}</div>
        {!items.length && <p className="notification-empty">No notifications yet.</p>}
        {items.slice(0, 8).map((item) => <div className={`notification-popover-item ${item.is_read ? '' : 'unread'}`} key={item.id}><div><strong>{item.title}</strong><p>{item.message}</p></div><time>{timeLabel(item.created_at)}</time></div>)}
      </div>}
    </div>
  );
}
