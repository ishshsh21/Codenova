import { useState } from 'react';
import { startGoogleLogin } from '../api/client';

export default function Login() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await startGoogleLogin();
      // Redirect to Google's consent screen. On return, the backend sets the
      // session cookie and redirects back here already signed in.
      window.location.href = res.authorization_url;
    } catch (err) {
      setBusy(false);
      const message = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(message || 'Could not start Google sign-in. Check the backend is configured and running.');
    }
  };

  return (
    <div className="login-screen">
      <div className="login-card">
        <span className="brand-mark login-mark" aria-hidden="true"><span className="brand-dot" /></span>
        <h1>Workday Signal</h1>
        <p className="login-sub">
          Reads your Gmail, extracts the tasks buried in it, and hands you back a
          prioritized agenda you can trust — with a reason for every priority.
        </p>
        <button className="btn-primary btn-lg" onClick={handleConnect} disabled={busy}>
          {busy ? 'Connecting…' : 'Sign in with Google'}
        </button>
        {error && <p className="login-error">{error}</p>}
        <p className="login-scope">Read-only access · gmail.readonly · never sends or modifies mail</p>
      </div>
    </div>
  );
}
