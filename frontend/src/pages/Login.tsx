import { useState } from 'react';
import { errorMessage, startGoogleLogin } from '../api/client';

export default function Login() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      // Google's consent screen redirects back to the backend, which sets the session cookie.
      window.location.href = (await startGoogleLogin()).authorization_url;
    } catch (err) {
      setBusy(false);
      setError(errorMessage(err, 'Could not start Google sign-in. Check the backend is configured and running.'));
    }
  };

  return (
    <div className="login">
      <div className="login-card">
        <span className="brand-mark brand-mark-lg" aria-hidden="true">✦</span>
        <h1>Codenova</h1>
        <p className="muted">
          Your college inbox, sorted. Codenova pulls the things you actually have to do out of Gmail,
          ranks them, and sets aside everything meant for other classes.
        </p>
        <button className="btn btn-primary btn-lg" onClick={signIn} disabled={busy}>{busy ? 'Opening Google…' : 'Sign in with Google'}</button>
        {error && <p className="banner banner-error">{error}</p>}
        <small className="muted">Read-only access. Codenova never sends, deletes or changes mail.</small>
      </div>
    </div>
  );
}
