import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { FyiGroup, FyiItem, User } from '../types';
import { claimFyi, getFyi } from '../api/client';
import { shortDateTime } from '../format';
import { useToast } from '../components/Toast';
import LinkifiedText from '../components/LinkifiedText';

const GROUPS: { id: FyiGroup | 'ALL'; label: string }[] = [
  { id: 'ALL', label: 'Everything' },
  { id: 'OTHER_CLASS', label: 'Other classes' },
  { id: 'NOTICE', label: 'Notices' },
  { id: 'NEWSLETTER', label: 'Newsletters' },
  { id: 'AUTOMATED', label: 'Automated' },
];

export default function Fyi({ user }: { user: User }) {
  const [items, setItems] = useState<FyiItem[] | null>(null);
  const [group, setGroup] = useState<FyiGroup | 'ALL'>('ALL');
  const [claiming, setClaiming] = useState<string | null>(null);
  const { showToast } = useToast();
  const navigate = useNavigate();

  useEffect(() => { getFyi().then(setItems); }, []);

  const claim = async (item: FyiItem) => {
    setClaiming(item.id);
    try {
      await claimFyi(item.id);
      setItems((current) => current?.filter((i) => i.id !== item.id) ?? null);
      showToast('Moved to your tasks.', 'success');
      navigate('/');
    } catch {
      showToast('Could not move that one. Try again.', 'error');
      setClaiming(null);
    }
  };

  if (!items) return <div className="loading">Loading…</div>;
  const visible = group === 'ALL' ? items : items.filter((i) => i.group === group);
  const count = (id: FyiGroup | 'ALL') => (id === 'ALL' ? items.length : items.filter((i) => i.group === id).length);

  return (
    <>
      <header className="page-head">
        <h1>FYI</h1>
        <p className="muted">
          Good to know, not yours to do. Nothing here is ranked or counted in your tasks.
          {user.my_classes.length > 0 && <> Your classes: <strong>{user.my_classes.join(', ')}</strong>.</>}
        </p>
      </header>

      <div className="segmented" role="tablist">
        {GROUPS.map((g) => (
          <button key={g.id} role="tab" aria-selected={group === g.id} className={group === g.id ? 'is-active' : ''} onClick={() => setGroup(g.id)}>
            {g.label} <span className="muted">{count(g.id)}</span>
          </button>
        ))}
      </div>

      {!visible.length && (
        <div className="empty">
          <p className="muted">
            {group === 'OTHER_CLASS' && !user.my_classes.length
              ? <>Add your class in <Link className="link" to="/profile">Profile</Link> and mail for other classes will land here.</>
              : 'Nothing here.'}
          </p>
        </div>
      )}

      <div className="stack">
        {visible.map((item) => (
          <article key={item.id} className="fyi">
            <div className="fyi-head">
              <span className={`badge badge-${item.group}`}>{item.reason}</span>
              <time className="muted">{shortDateTime(item.internal_date)}</time>
            </div>
            <strong>{item.subject || '(no subject)'}</strong>
            <p className="muted">{item.sender_name || item.sender_email} · <LinkifiedText text={item.snippet} /></p>
            <div className="row-gap">
              <a className="link" href={item.gmail_url} target="_blank" rel="noopener noreferrer">Open in Gmail ↗</a>
              <button className="btn btn-quiet" disabled={claiming === item.id} onClick={() => claim(item)}>This is mine</button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
