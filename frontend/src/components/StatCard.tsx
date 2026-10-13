export default function StatCard({
  label, value, tone = 'default', onClick, active = false,
}: {
  label: string;
  value: number | string;
  tone?: 'default' | 'critical' | 'muted';
  onClick?: () => void;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      className={`stat-card tone-${tone}${active ? ' is-active' : ''}`}
      onClick={onClick ?? (() => window.dispatchEvent(new CustomEvent('kpi-filter', { detail: label })))}
      aria-pressed={active}
      style={{ color: 'inherit', font: 'inherit', textAlign: 'left' }}
    >
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </button>
  );
}
