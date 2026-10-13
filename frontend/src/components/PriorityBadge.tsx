const LABELS: Record<string, string> = {
  P0: 'Critical',
  P1: 'High',
  P2: 'Medium',
  P3: 'Low',
  P4: 'Info',
};

export default function PriorityBadge({ priority }: { priority: string }) {
  return (
    <span className={`priority-badge priority-${priority}`}>
      <span className="priority-dot" />
      {priority} · {LABELS[priority] ?? priority}
    </span>
  );
}
