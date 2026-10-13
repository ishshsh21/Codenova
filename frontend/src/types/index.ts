export interface User {
  id: string;
  email: string;
  name: string;
  timezone: string;
  workday_start: string;
  workday_end: string;
  default_scan_days: number;
  notify_scan_completion: boolean;
  vip_senders: string[];
  ignored_senders: string[];
}

export interface GmailStatus {
  connected: boolean;
  google_account_email?: string;
  last_synced_at?: string;
  watch_active: boolean;
}

export interface ScanRun {
  id: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | string;
  start_date?: string | null;
  end_date?: string | null;
  gmail_query: string;
  messages_fetched: number;
  messages_processed: number;
  tasks_created: number;
  tasks_updated: number;
  duration_ms: number;
  stage: string;
  progress: number;
  progress_total: number;
  connection_id?: string | null;
  account_email?: string | null;
  account_label?: string | null;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ScanStart {
  id: string;
  status: string;
  start_date?: string | null;
  end_date?: string | null;
  gmail_query: string;
  created_at: string;
}

export interface Notification {
  id: string;
  scan_id?: string | null;
  kind: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface DataSummary {
  imported_emails: number;
  tasks: number;
  scans: number;
  notifications: number;
  gmail_connected: boolean;
  gmail_scopes: string[];
}

export interface SyncRequest {
  start_date?: string; // YYYY-MM-DD
  end_date?: string;   // YYYY-MM-DD
}

export interface TaskSource {
  message_id: string;
  gmail_thread_id: string;
  internal_date?: string | null;
  gmail_url: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  relationship_type: string;
}

export type Priority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4';

export interface Task {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: Priority;
  priority_score: number;
  priority_reasons: string[];
  action_type: string;
  deadline?: string | null;
  deadline_raw?: string | null;
  deadline_confidence: number;
  owner_type: string;
  owner_label: string;
  project?: string | null;
  project_confidence: number;
  estimated_effort_minutes: number;
  confidence: number;
  is_blocking: boolean;
  notes: string;
  snoozed_until?: string | null;
  depends_on: string[];
  sources: TaskSource[];
  calendar_synced?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgendaTask {
  id: string;
  title: string;
  priority: string;
  priority_score: number;
  deadline?: string | null;
  estimated_effort_minutes: number;
  blocking: boolean;
  reason: string[];
  scheduled_time?: string | null;
  source_thread_id?: string | null;
}

export interface DailyAgenda {
  date: string;
  summary: {
    actionable: number;
    critical: number;
    due_today: number;
    overdue: number;
    this_week: number;
  };
  task_ids: {
    due_today: string[];
    overdue: string[];
    this_week: string[];
  };
  timeline: AgendaTask[];
  no_action_count: number;
}

export interface WeeklyAgenda {
  week_start: string;
  week_end: string;
  days: Record<string, AgendaTask[]>;
  later: AgendaTask[];
}

export interface FollowUpAlert {
  task_id: string;
  title: string;
  message: string;
  hours_remaining: number;
}

export interface AssistantMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface AssistantChatResponse {
  message: string;
  action_taken?: string | null;
}

// ---- Google Calendar (Today) ----
export interface CalendarStatus {
  connected: boolean;
  google_account_email?: string | null;
  last_synced_at?: string | null;
  needs_reauth: boolean;
  error?: string | null;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string;
  html_link: string;
  origin: string;
}

export interface CalendarSyncResult {
  connected: boolean;
  changed: boolean;
  created: number;
  updated: number;
  deleted: number;
  pulled: number;
  conflicts: { task_id: string; title: string; conflicts_with: { title: string }[] }[];
  error?: string | null;
  needs_reauth: boolean;
  events: CalendarEvent[];
}

// ---- Multiple Gmail accounts ----
export interface GmailAccount {
  id: string;
  email: string;
  label: string;
  is_primary: boolean;
  last_synced_at?: string | null;
}

export interface GmailAccounts {
  accounts: GmailAccount[];
  selected: string; // an account id, or "all"
}
