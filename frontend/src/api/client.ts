import axios from 'axios';
import type {
  User, GmailStatus, ScanRun, ScanStart, SyncRequest, Task, DailyAgenda, WeeklyAgenda, FollowUpAlert, Notification, DataSummary, AssistantMessage, AssistantChatResponse,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true, // send the session cookie set by /api/auth/google/callback
});

// ---- Auth ----
export const startGoogleLogin = async (): Promise<{ authorization_url: string }> => {
  const { data } = await api.get('/api/auth/google');
  return data;
};

export const getMe = async (): Promise<User> => {
  const { data } = await api.get('/api/auth/me');
  return data;
};

export const logout = async (): Promise<void> => {
  await api.post('/api/auth/logout');
};

export const deleteAccount = async (): Promise<void> => {
  await api.delete('/api/auth/account');
};

export const updateSettings = async (settings: Partial<User>): Promise<User> => {
  const { data } = await api.patch('/api/auth/settings', settings);
  return data;
};

export const getDataSummary = async (): Promise<DataSummary> => {
  const { data } = await api.get('/api/auth/data-summary');
  return data;
};

export const deleteImportedData = async (): Promise<void> => {
  await api.delete('/api/auth/imported-data');
};

// ---- Gmail ----
export const getGmailStatus = async (): Promise<GmailStatus> => {
  const { data } = await api.get('/api/gmail/status');
  return data;
};

export const syncGmail = async (range?: SyncRequest): Promise<ScanStart> => {
  const { data } = await api.post('/api/gmail/sync', range ?? {});
  return data;
};

export const getScan = async (id: string): Promise<ScanRun> => {
  const { data } = await api.get(`/api/gmail/scans/${id}`);
  return data;
};

export const rerunScan = async (id: string): Promise<ScanStart> => {
  const { data } = await api.post(`/api/gmail/scans/${id}/rerun`);
  return data;
};

export const deleteScan = async (id: string): Promise<void> => {
  await api.delete(`/api/gmail/scans/${id}`);
};

export const getScans = async (): Promise<ScanRun[]> => {
  const { data } = await api.get('/api/gmail/scans');
  return data;
};

export const getNotifications = async (): Promise<Notification[]> => {
  const { data } = await api.get('/api/gmail/notifications');
  return data;
};

export const markNotificationsRead = async (): Promise<void> => {
  await api.post('/api/gmail/notifications/read-all');
};

export const disconnectGmail = async (): Promise<void> => {
  await api.delete('/api/gmail/disconnect');
};

// ---- Tasks ----
export const listTasks = async (params?: { status?: string; priority?: string }): Promise<Task[]> => {
  const { data } = await api.get('/api/tasks', { params });
  return data;
};

export const getTask = async (id: string): Promise<Task> => {
  const { data } = await api.get(`/api/tasks/${id}`);
  return data;
};

export const updateTask = async (id: string, payload: Partial<Task>): Promise<Task> => {
  const { data } = await api.patch(`/api/tasks/${id}`, payload);
  return data;
};

export const completeTask = async (id: string): Promise<Task> => {
  const { data } = await api.post(`/api/tasks/${id}/complete`);
  return data;
};

export const dismissTask = async (id: string): Promise<Task> => {
  const { data } = await api.post(`/api/tasks/${id}/dismiss`);
  return data;
};

export const sendTaskFeedback = async (id: string, feedback_type: string, new_value?: Record<string, unknown>): Promise<void> => {
  await api.post(`/api/tasks/${id}/feedback`, { feedback_type, new_value });
};

// ---- Agenda ----
export const getDailyAgenda = async (): Promise<DailyAgenda> => {
  const { data } = await api.get('/api/agenda/today');
  return data;
};

export const getWeeklyAgenda = async (): Promise<WeeklyAgenda> => {
  const { data } = await api.get('/api/agenda/week');
  return data;
};

export const replanAgenda = async (): Promise<DailyAgenda> => {
  const { data } = await api.post('/api/agenda/replan');
  return data;
};

export const getFollowUps = async (): Promise<{ alerts: FollowUpAlert[] }> => {
  const { data } = await api.get('/api/agenda/follow-ups');
  return data;
};

export const chatWithAssistant = async (message: string, history: AssistantMessage[]): Promise<AssistantChatResponse> => {
  const { data } = await api.post('/api/assistant/chat', { message, history });
  return data;
};

// ---- Search ----
export const search = async (q: string): Promise<{ tasks: Partial<Task>[]; emails: unknown[] }> => {
  const { data } = await api.get('/api/search', { params: { q } });
  return data;
};
