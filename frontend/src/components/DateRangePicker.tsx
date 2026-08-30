import { useState } from 'react';

export interface DateRange {
  start_date?: string;
  end_date?: string;
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

export default function DateRangePicker({
  onSync, busy, defaultScanDays,
}: { onSync: (range: DateRange) => void; busy: boolean; defaultScanDays: number }) {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSync = () => {
    if (start && end && start > end) {
      setError('Start date must be before end date');
      return;
    }
    setError(null);
    const range: DateRange = {};
    if (start) range.start_date = start;
    if (end) range.end_date = end;
    setOpen(false);
    onSync(range);
  };

  const handleQuickSync = () => onSync({});

  return (
    <div className="sync-control">
      <div className="sync-buttons">
        <button className="btn-primary" onClick={handleQuickSync} disabled={busy}>
          {busy ? 'Syncing…' : 'Sync Gmail'}
        </button>
        <button
          className="btn-secondary"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          Scan range {open ? '▴' : '▾'}
        </button>
      </div>

      {open && (
        <div className="range-popover">
          <div className="range-field">
            <label htmlFor="range-start">From</label>
            <input
              id="range-start"
              type="date"
              value={start}
              max={end || todayISO()}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div className="range-field">
            <label htmlFor="range-end">To</label>
            <input
              id="range-end"
              type="date"
              value={end}
              min={start}
              max={todayISO()}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>
          {error && <span className="range-error">{error}</span>}
          <div className="range-actions">
            <button
              className="btn-ghost"
              onClick={() => { setStart(''); setEnd(''); setError(null); }}
              disabled={!start && !end}
            >
              Clear
            </button>
            <button className="btn-primary" onClick={handleSync} disabled={busy}>
              {busy ? 'Scanning…' : 'Scan this range'}
            </button>
          </div>
          <p className="range-hint">
            Leave both blank to scan the default window (last {defaultScanDays} days).
          </p>
        </div>
      )}
    </div>
  );
}
