import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import type { User } from './types';
import { getMe } from './api/client';
import Shell from './components/Shell';
import Login from './pages/Login';
import Today from './pages/Today';
import Week from './pages/Week';
import ScanHistory from './pages/ScanHistory';
import { ToastProvider } from './components/Toast';
import Settings from './pages/Settings';

function RequireAuth({ user, loading, children }: { user: User | null; loading: boolean; children: React.ReactNode }) {
  const location = useLocation();
  if (loading) return <div className="loading-state">Loading…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = () => {
    getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  };

  useEffect(() => { refreshUser(); }, []);

  return (
    <ToastProvider>
      <BrowserRouter>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route
          path="/"
          element={
            <RequireAuth user={user} loading={loading}>
              <Shell user={user}><Today /></Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/today"
          element={
            <RequireAuth user={user} loading={loading}>
              <Shell user={user}><Today workspaceOnly /></Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/week"
          element={
            <RequireAuth user={user} loading={loading}>
              <Shell user={user}><Week /></Shell>
            </RequireAuth>
          }
        />
        <Route
          path="/scans"
          element={
            <RequireAuth user={user} loading={loading}>
              <Shell user={user}><ScanHistory /></Shell>
            </RequireAuth>
          }
        />
        <Route path="/settings" element={<RequireAuth user={user} loading={loading}><Shell user={user}><Settings /></Shell></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
