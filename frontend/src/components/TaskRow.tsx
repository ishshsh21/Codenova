import type { TaskCard } from '../types';
import { PRIORITY_LABEL } from '../format';

export function PriorityTag({ priority }: { priority: TaskCard['priority'] }) {
  return <span className={`ptag ptag-${priority}`}>{PRIORITY_LABEL[priority]}</span>;
}

/** One task line. `meta` is whatever time detail the host section cares about. */
export default function TaskRow({ task, meta, onOpen }: { task: TaskCard; meta?: string; onOpen: (id: string) => void }) {
  return (
    <button className={`task-row p-${task.priority}`} onClick={() => onOpen(task.id)}>
      <span className="task-row-main">
        <strong>{task.title}</strong>
        <small>{task.reason[0] ?? 'Open task'}</small>
      </span>
      <span className="task-row-side">
        <PriorityTag priority={task.priority} />
        {meta && <small>{meta}</small>}
      </span>
    </button>
  );
}
