import { useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import type { User } from './types';
import { getMe } from './api/client';
import { ToastProvider } from './components/Toast';
import Shell from './components/Shell';
import Login from './pages/Login';
import Now from './pages/Now';
import Planner from './pages/Planner';
import Fyi from './pages/Fyi';
import Sync from './pages/Sync';
import Profile from './pages/Profile';

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(() => {
    return getMe().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  useEffect(() => { refreshUser(); }, [refreshUser]);

  if (loading) return <div className="loading">Loading…</div>;

  return (
    <ToastProvider>
      <BrowserRouter>
        {!user ? (
          <Routes><Route path="*" element={<Login />} /></Routes>
        ) : (
          <Shell>
            <Routes>
              <Route path="/" element={<Now user={user} />} />
              <Route path="/planner" element={<Planner />} />
              <Route path="/fyi" element={<Fyi user={user} />} />
              <Route path="/sync" element={<Sync user={user} onUserChange={setUser} />} />
              <Route path="/profile" element={<Profile user={user} onUserChange={setUser} />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Shell>
        )}
      </BrowserRouter>
    </ToastProvider>
  );
}
