export type Priority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4';
export type Audience = 'MINE' | 'OTHER_CLASS' | 'GENERAL';

export interface User {
  id: string;
  email: string;
  name: string;
  default_scan_days: number;
  notify_scan_completion: boolean;
  vip_senders: string[];
  ignored_senders: string[];
  my_classes: string[];
}

export interface GmailStatus {
  connected: boolean;
  google_account_email?: string;
  last_synced_at?: string;
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
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface ScanStart {
  id: string;
  status: string;
  created_at: string;
}

export interface Notification {
  id: string;
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

export interface ScanRange {
  start_date?: string; // YYYY-MM-DD
  end_date?: string;   // YYYY-MM-DD
}

export interface TaskSource {
  message_id: string;
  internal_date?: string | null;
  gmail_url: string;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  relationship_type: string;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: Priority;
  priority_reasons: string[];
  deadline?: string | null;
  deadline_raw?: string | null;
  deadline_confidence: number;
  owner_label: string;
  owner_type: string;
  estimated_effort_minutes: number;
  is_blocking: boolean;
  notes: string;
  snoozed_until?: string | null;
  audience: Audience;
  sources: TaskSource[];
}

export interface TaskCard {
  id: string;
  title: string;
  priority: Priority;
  deadline?: string | null;
  estimated_effort_minutes: number;
  blocking: boolean;
  reason: string[];
}

export interface NowView {
  date: string;
  overdue: TaskCard[];
  due_today: TaskCard[];
  up_next: TaskCard[];
  open_count: number;
  fyi_count: number;
  planned_minutes_today: number;
}

export interface PlannerView {
  week_start: string;
  week_end: string;
  days: Record<string, TaskCard[]>;
  undated: TaskCard[];
}

export type FyiGroup = 'OTHER_CLASS' | 'NEWSLETTER' | 'NOTICE' | 'AUTOMATED';

export interface FyiItem {
  id: string;
  group: FyiGroup;
  subject: string;
  sender_name: string;
  sender_email: string;
  snippet: string;
  internal_date?: string | null;
  gmail_url: string;
  audience_label: string;
  reason: string;
}

export interface AssistantMessage {
  role: 'user' | 'assistant';
  content: string;
}
