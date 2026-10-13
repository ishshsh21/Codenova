import axios from 'axios';
import type {
  AssistantMessage, DataSummary, FyiItem, GmailStatus, Notification, NowView, PlannerView,
  ScanRange, ScanRun, ScanStart, Task, User,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// withCredentials sends the session cookie set by /api/auth/google/callback.
export const api = axios.create({ baseURL: BASE_URL, withCredentials: true });

const get = async <T>(url: string): Promise<T> => (await api.get<T>(url)).data;

export function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string | { msg: string }[] } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail[0]?.msg ?? fallback;
  return fallback;
}

// ---- Account ----
export const startGoogleLogin = () => get<{ authorization_url: string }>('/api/auth/google');
export const getMe = () => get<User>('/api/auth/me');
export const logout = async () => { await api.post('/api/auth/logout'); };
export const updateProfile = async (patch: Partial<User>): Promise<User> => (await api.patch('/api/auth/settings', patch)).data;
export const getDataSummary = () => get<DataSummary>('/api/auth/data-summary');
export const deleteImportedData = async () => { await api.delete('/api/auth/imported-data'); };
export const deleteAccount = async () => { await api.delete('/api/auth/account'); };

// ---- Gmail sync ----
export const getGmailStatus = () => get<GmailStatus>('/api/gmail/status');
export const startScan = async (range: ScanRange = {}): Promise<ScanStart> => (await api.post('/api/gmail/sync', range)).data;
export const getScan = (id: string) => get<ScanRun>(`/api/gmail/scans/${id}`);
export const getScans = () => get<ScanRun[]>('/api/gmail/scans');
export const rerunScan = async (id: string): Promise<ScanStart> => (await api.post(`/api/gmail/scans/${id}/rerun`)).data;
export const deleteScan = async (id: string) => { await api.delete(`/api/gmail/scans/${id}`); };
export const disconnectGmail = async () => { await api.delete('/api/gmail/disconnect'); };

// ---- Notifications ----
export const getNotifications = () => get<Notification[]>('/api/gmail/notifications');
export const markNotificationsRead = async () => { await api.post('/api/gmail/notifications/read-all'); };

// ---- Views ----
export const getNow = () => get<NowView>('/api/agenda/now');
export const getPlanner = () => get<PlannerView>('/api/agenda/planner');
export const getFyi = () => get<FyiItem[]>('/api/fyi');
export const claimFyi = async (id: string): Promise<{ task_id: string }> => (await api.post(`/api/fyi/${id}/claim`)).data;

// ---- Tasks ----
export const getTask = (id: string) => get<Task>(`/api/tasks/${id}`);
export const updateTask = async (id: string, patch: Partial<Task>): Promise<Task> => (await api.patch(`/api/tasks/${id}`, patch)).data;
export const completeTask = async (id: string) => { await api.post(`/api/tasks/${id}/complete`); };
export const dismissTask = async (id: string) => { await api.post(`/api/tasks/${id}/dismiss`); };
export const markNotMine = async (id: string) => { await api.post(`/api/tasks/${id}/feedback`, { feedback_type: 'not_my_task' }); };

// ---- Assistant ----
export const askAssistant = async (message: string, history: AssistantMessage[]): Promise<{ message: string }> =>
  (await api.post('/api/assistant/chat', { message, history })).data;
