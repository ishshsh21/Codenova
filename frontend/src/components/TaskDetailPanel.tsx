import { useEffect, useState } from 'react';
import type { Priority, Task } from '../types';
import { getTask, completeTask, dismissTask, sendTaskFeedback, updateTask } from '../api/client';
import PriorityBadge from './PriorityBadge';
import LinkifiedText from './LinkifiedText';

function fmtDeadline(iso?: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function TaskDetailPanel({
  taskId, onClose, onChanged,
}: { taskId: string; onClose: () => void; onChanged: () => void }) {
  const [task, setTask] = useState<Task | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<Priority>('P3');
  const [deadline, setDeadline] = useState('');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    let cancelled = false;
    getTask(taskId).then((t) => {
      if (!cancelled) {
        setTask(t);
        setTitle(t.title);
        setPriority(t.priority);
        setDeadline(t.deadline ? new Date(t.deadline).toISOString().slice(0, 16) : '');
        setNotes(t.notes || '');
      }
    });
    return () => { cancelled = true; };
  }, [taskId]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      onChanged();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const saveEdits = async () => {
    if (!task || !title.trim()) return;
    await act(async () => {
      const updated = await updateTask(task.id, {
        title: title.trim(), priority, deadline: deadline ? new Date(deadline).toISOString() : null, notes,
      });
      setTask(updated);
      setEditing(false);
    });
  };

  const snooze = async (days: number | null) => {
    if (!task) return;
    await act(async () => {
      const updated = await updateTask(task.id, {
        snoozed_until: days === null ? null : new Date(Date.now() + days * 86400000).toISOString(),
      });
      setTask(updated);
    });
  };

  return (
    <div className="panel-overlay" onClick={onClose}>
      <aside className="panel" onClick={(e) => e.stopPropagation()}>
        {!task ? (
          <div className="panel-loading">Loading…</div>
        ) : (
          <>
            <div className="panel-header">
              <PriorityBadge priority={task.priority} />
              <button className="btn-icon" onClick={onClose} aria-label="Close">×</button>
            </div>

            {editing ? (
              <div className="edit-task-form">
                <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
                <div className="edit-task-row">
                  <label>Priority<select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
                  {(['P0', 'P1', 'P2', 'P3', 'P4'] as Priority[]).map((value) => <option key={value}>{value}</option>)}
                  </select></label>
                  <label>Deadline<input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} /></label>
                </div>
                <label>Personal notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} /></label>
                <div className="panel-actions edit-actions">
                  <button className="btn-primary" disabled={busy} onClick={saveEdits}>Save changes</button>
                  <button className="btn-ghost" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
                </div>
              </div>
            ) : <h2 className="panel-title">{task.title}</h2>}

            <div className="panel-meta-grid">
              <div>
                <span className="meta-label">Deadline</span>
                <span className="meta-value">
                  {fmtDeadline(task.deadline) ?? task.deadline_raw ?? '—'}
                  {task.deadline_confidence < 0.6 && task.deadline && (
                    <span className="low-confidence-tag">unconfirmed</span>
                  )}
                </span>
              </div>
              <div>
                <span className="meta-label">Owner</span>
                <span className="meta-value">{task.owner_label || task.owner_type}</span>
              </div>
              <div>
                <span className="meta-label">Effort</span>
                <span className="meta-value">{task.estimated_effort_minutes} min</span>
              </div>
              <div>
                <span className="meta-label">Project</span>
                <span className="meta-value">{task.project ?? '—'}</span>
              </div>
              <div>
                <span className="meta-label">AI confidence</span>
                <span className="meta-value">{Math.round(task.confidence * 100)}%</span>
              </div>
              <div>
                <span className="meta-label">Status</span>
                <span className="meta-value">{task.status}</span>
              </div>
            </div>

            {task.is_blocking && <div className="blocking-tag">⛔ Blocks other work</div>}

            {!editing && (
              <div className="panel-section">
                <span className="panel-section-title">Plan</span>
                <div className="snooze-actions">
                  <button className="btn-secondary" disabled={busy} onClick={() => snooze(1)}>Snooze 1 day</button>
                  <button className="btn-secondary" disabled={busy} onClick={() => snooze(7)}>Snooze 1 week</button>
                  {task.snoozed_until && <button className="btn-ghost" disabled={busy} onClick={() => snooze(null)}>Wake task</button>}
                </div>
                {task.snoozed_until && <span className="snooze-note">Snoozed until {fmtDeadline(task.snoozed_until)}</span>}
              </div>
            )}

            <div className="panel-section">
              <span className="panel-section-title">Why this priority</span>
              <ul className="reason-list">
                {task.priority_reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>

            {task.description && (
              <div className="panel-section">
                <span className="panel-section-title">Details</span>
              <p className="panel-description"><LinkifiedText text={task.description} /></p>
              </div>
            )}

            {!editing && task.notes && (
              <div className="panel-section">
                <span className="panel-section-title">Personal notes</span>
                <p className="panel-description">{task.notes}</p>
              </div>
            )}

            <div className="panel-section">
              <span className="panel-section-title">Source emails ({task.sources.length})</span>
              <div className="source-list">
                {task.sources.map((s) => (
                  <div className="source-item" key={s.message_id}>
                    <div className="source-top">
                      <span className="source-sender">{s.sender_name || s.sender_email}</span>
                      <span className={`source-relationship rel-${s.relationship_type}`}>{s.relationship_type}</span>
                    </div>
                    <div className="source-subject">{s.subject}</div>
                    <div className="source-date">Received {fmtDeadline(s.internal_date)}</div>
                    <div className="source-snippet"><LinkifiedText text={s.snippet} /></div>
                    <a className="source-open-link" href={s.gmail_url} target="_blank" rel="noopener noreferrer">
                      Open original email in Gmail ↗
                    </a>
                  </div>
                ))}
              </div>
            </div>

            <div className="panel-actions">
              {!editing && <button className="btn-secondary" disabled={busy} onClick={() => setEditing(true)}>Edit task</button>}
              <button className="btn-primary" disabled={busy} onClick={() => act(() => completeTask(task.id))}>
                Mark complete
              </button>
              <button className="btn-secondary" disabled={busy} onClick={() => act(() => dismissTask(task.id))}>
                Dismiss
              </button>
              <button
                className="btn-secondary"
                disabled={busy}
                onClick={() => act(() => sendTaskFeedback(task.id, 'not_my_task'))}
              >
                Not my task
              </button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
