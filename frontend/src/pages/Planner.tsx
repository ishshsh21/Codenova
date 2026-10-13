import { useCallback, useEffect, useState } from 'react';
import type { PlannerView } from '../types';
import { getPlanner } from '../api/client';
import { dayLabel, timeOfDay } from '../format';
import TaskRow from '../components/TaskRow';
import TaskSheet from '../components/TaskSheet';

export default function Planner() {
  const [view, setView] = useState<PlannerView | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const load = useCallback(() => { getPlanner().then(setView); }, []);
  useEffect(() => { load(); }, [load]);

  if (!view) return <div className="loading">Loading…</div>;

  return (
    <>
      <header className="page-head">
        <h1>Planner</h1>
        <p className="muted">What's due over the next seven days, by deadline.</p>
      </header>

      <div className="week">
        {Object.entries(view.days).map(([date, tasks]) => {
          const day = dayLabel(date);
          return (
            <section key={date} className={`day${day.isToday ? ' is-today' : ''}`}>
              <header className="day-head"><strong>{day.weekday}</strong><span>{day.date}</span></header>
              {tasks.length
                ? <div className="stack">{tasks.map((t) => <TaskRow key={t.id} task={t} meta={timeOfDay(t.deadline)} onOpen={setOpenId} />)}</div>
                : <p className="muted day-free">Free</p>}
            </section>
          );
        })}
      </div>

      {view.undated.length > 0 && (
        <section className="group">
          <header className="group-head"><h2>No date yet</h2><span className="muted">Open one to set a deadline</span></header>
          <div className="stack">{view.undated.map((t) => <TaskRow key={t.id} task={t} onOpen={setOpenId} />)}</div>
        </section>
      )}

      {openId && <TaskSheet taskId={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </>
  );
}
