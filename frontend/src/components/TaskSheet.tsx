import { useEffect, useState } from 'react';
import type { Priority, Task } from '../types';
import { completeTask, dismissTask, getTask, markNotMine, updateTask } from '../api/client';
import { PRIORITY_LABEL, shortDateTime } from '../format';
import { useToast } from './Toast';
import LinkifiedText from './LinkifiedText';
import { PriorityTag } from './TaskRow';

const toLocalInput = (iso?: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

/** The one place a task is read, edited, snoozed or closed. */
export default function TaskSheet({ taskId, onClose, onChanged }: { taskId: string; onClose: () => void; onChanged: () => void }) {
  const [task, setTask] = useState<Task | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ title: '', priority: 'P3' as Priority, deadline: '', notes: '' });
  const { showToast } = useToast();

  useEffect(() => {
    let live = true;
    getTask(taskId).then((t) => {
      if (!live) return;
      setTask(t);
      setDraft({ title: t.title, priority: t.priority, deadline: toLocalInput(t.deadline), notes: t.notes || '' });
    });
    return () => { live = false; };
  }, [taskId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await action();
      showToast(done, 'success');
      onChanged();
      onClose();
    } catch {
      showToast('That did not go through. Try again.', 'error');
      setBusy(false);
    }
  };

  if (!task) {
    return <div className="scrim" onClick={onClose}><aside className="drawer"><p className="muted">Loading…</p></aside></div>;
  }

  const dirty = draft.title !== task.title || draft.priority !== task.priority
    || draft.deadline !== toLocalInput(task.deadline) || draft.notes !== (task.notes || '');
  const snooze = (days: number | null) => updateTask(task.id, {
    snoozed_until: days === null ? null : new Date(Date.now() + days * 86400000).toISOString(),
  });

  return (
    <div className="scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={task.title} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head"><PriorityTag priority={task.priority} /><button className="btn btn-icon" aria-label="Close" onClick={onClose}>×</button></header>

        <div className="drawer-body">
          <input className="title-input" aria-label="Title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />

          <section>
            <h3>Why it's ranked here</h3>
            <ul className="reasons">{task.priority_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </section>

          <section className="field-grid">
            <label>Priority
              <select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value as Priority })}>
                {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
              </select>
            </label>
            <label>Due
              <input type="datetime-local" value={draft.deadline} onChange={(e) => setDraft({ ...draft, deadline: e.target.value })} />
              {!task.deadline && task.deadline_raw && <small className="muted">Email says “{task.deadline_raw}”</small>}
            </label>
            <label className="span-2">Notes
              <textarea rows={3} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            </label>
          </section>
          {dirty && (
            <button className="btn btn-primary" disabled={busy || !draft.title.trim()} onClick={() => run(() => updateTask(task.id, {
              title: draft.title.trim(), priority: draft.priority, notes: draft.notes,
              deadline: draft.deadline ? new Date(draft.deadline).toISOString() : null,
            }), 'Saved.')}>Save changes</button>
          )}

          <section>
            <h3>Later</h3>
            <div className="row-gap">
              <button className="btn" disabled={busy} onClick={() => run(() => snooze(1), 'Snoozed until tomorrow.')}>Snooze a day</button>
              <button className="btn" disabled={busy} onClick={() => run(() => snooze(7), 'Snoozed for a week.')}>Snooze a week</button>
              {task.snoozed_until && <button className="btn" disabled={busy} onClick={() => run(() => snooze(null), 'Task is back.')}>Wake now</button>}
            </div>
            {task.snoozed_until && <small className="muted">Snoozed until {shortDateTime(task.snoozed_until)}</small>}
          </section>

          <section>
            <h3>From your inbox</h3>
            {task.sources.map((s) => (
              <article className="source" key={s.message_id}>
                <div className="source-head"><strong>{s.sender_name || s.sender_email}</strong><time>{shortDateTime(s.internal_date)}</time></div>
                <p className="source-subject">{s.subject}</p>
                <p className="muted"><LinkifiedText text={s.snippet} /></p>
                <a className="link" href={s.gmail_url} target="_blank" rel="noopener noreferrer">Open in Gmail ↗</a>
              </article>
            ))}
            {!task.sources.length && <p className="muted">Added by hand.</p>}
          </section>
        </div>

        <footer className="drawer-foot">
          <button className="btn btn-primary" disabled={busy} onClick={() => run(() => completeTask(task.id), 'Done. Nice.')}>Mark done</button>
          <button className="btn" disabled={busy} onClick={() => run(() => markNotMine(task.id), 'Removed: not yours.')}>Not mine</button>
          <button className="btn btn-quiet" disabled={busy} onClick={() => run(() => dismissTask(task.id), 'Dismissed.')}>Dismiss</button>
        </footer>
      </aside>
    </div>
  );
}
