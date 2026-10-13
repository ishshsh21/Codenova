import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { NowView, TaskCard, User } from '../types';
import { getNow } from '../api/client';
import { minutes, shortDate, timeOfDay } from '../format';
import TaskRow from '../components/TaskRow';
import TaskSheet from '../components/TaskSheet';

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

function Group({ title, hint, tasks, meta, onOpen }: {
  title: string; hint: string; tasks: TaskCard[]; meta: (t: TaskCard) => string; onOpen: (id: string) => void;
}) {
  if (!tasks.length) return null;
  return (
    <section className="group">
      <header className="group-head"><h2>{title}</h2><span className="muted">{hint}</span></header>
      <div className="stack">{tasks.map((t) => <TaskRow key={t.id} task={t} meta={meta(t)} onOpen={onOpen} />)}</div>
    </section>
  );
}

export default function Now({ user }: { user: User }) {
  const [view, setView] = useState<NowView | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const load = useCallback(() => { getNow().then(setView); }, []);
  useEffect(() => { load(); }, [load]);

  if (!view) return <div className="loading">Loading…</div>;
  const nothing = !view.overdue.length && !view.due_today.length && !view.up_next.length;

  return (
    <>
      <header className="page-head">
        <h1>{greeting()}, {user.name.split(' ')[0] || 'there'}</h1>
        <p className="muted">
          {view.open_count} open task{view.open_count === 1 ? '' : 's'}
          {view.planned_minutes_today > 0 && <> · about {minutes(view.planned_minutes_today)} of work due by tonight</>}
          {view.fyi_count > 0 && <> · <Link className="link" to="/fyi">{view.fyi_count} FYI item{view.fyi_count === 1 ? '' : 's'}</Link> kept out of your way</>}
        </p>
      </header>

      {!user.my_classes.length && (
        <div className="banner">
          Add your class in <Link className="link" to="/profile">Profile</Link> so mail meant for other classes stops showing up as your work.
        </div>
      )}

      {nothing && (
        <div className="empty">
          <strong>You're clear.</strong>
          <p className="muted">Nothing needs you right now. <Link className="link" to="/sync">Sync Gmail</Link> to pull in new mail.</p>
        </div>
      )}

      <Group title="Overdue" hint="Past their deadline" tasks={view.overdue} meta={(t) => `was due ${shortDate(t.deadline)}`} onOpen={setOpenId} />
      <Group title="Due today" hint="Before midnight" tasks={view.due_today} meta={(t) => timeOfDay(t.deadline)} onOpen={setOpenId} />
      <Group title="Up next" hint="Highest priority of the rest" tasks={view.up_next} meta={(t) => minutes(t.estimated_effort_minutes)} onOpen={setOpenId} />

      {openId && <TaskSheet taskId={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </>
  );
}
