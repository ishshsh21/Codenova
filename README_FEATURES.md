# Workday Signal Features

Workday Signal is a Gmail-only workday assistant. It reads Gmail with the
read-only `gmail.readonly` scope, extracts actionable work, explains priority,
and organizes tasks into a daily and weekly agenda.

## Product Features

### Authentication and privacy

- Google OAuth 2.0 sign-in with PKCE.
- Secure HTTP-only session cookie.
- Encrypted Gmail refresh-token storage.
- Gmail can be disconnected without deleting the user account.
- Privacy dashboard showing stored email, task, scan, and notification counts.
- Delete imported data while keeping the account and Gmail connection.
- Permanently delete the account and all associated data.

### Gmail scanning

- Default scan window configured per user.
- Custom inclusive start and end dates.
- Gmail search query shown for every scan.
- Background scanning so the dashboard remains usable.
- Bounded concurrent Gmail fetching and AI extraction for faster scans.
- Configurable worker count through `SYNC_WORKER_COUNT` (default: 8).
- Progress stages: fetching emails, processing emails, and building the agenda.
- Idempotent message ingestion prevents duplicate imported messages.
- Re-run any previous scan as a new scan run.
- Delete scan history without deleting imported Gmail data or tasks.

### Notifications

- Toast when a scan starts.
- Toast when a scan completes or fails.
- Persisted scan notifications.
- Notification bell with unread count.
- Mark-all-as-read support.
- Recent notification history on the Scan History page.

### AI task intelligence

- Classifies emails into action, information, newsletter, meeting, completed,
  waiting, follow-up, and automated categories.
- Extracts task title, action type, owner, deadline, project, effort, and
  blocking status.
- Deterministic heuristic fallback when Azure OpenAI is unavailable.
- Prompt-injection protection for email content.
- Priority scoring with human-readable reasons.
- Duplicate and follow-up task detection.
- Dependency and blocking-task detection.
- User-defined VIP sender priority boost.
- User-defined ignored senders excluded from task processing.

### Task management

- Daily timeline and weekly agenda.
- Focus-next list with the top three tasks.
- Estimated workload summary.
- Search and priority filtering on the Today page.
- Open, complete, dismiss, and mark-not-my-task actions.
- Edit task title, priority, deadline, and personal notes.
- Snooze tasks for one day or one week.
- Wake snoozed tasks early.
- Confidence and priority explanations.
- Related source emails for every task.
- Source received date and time.
- Clickable links in email details and snippets.
- Compact link labels opening in a new tab.
- Open original email thread in Gmail.

### Google Calendar (Today page)

- "Connect Calendar" (separate `calendar.events` grant); disconnect any time.
- Two-way sync: tasks with a deadline become events (start = deadline, length = estimated effort);
  creating, renaming, rescheduling, completing or dismissing a task updates its event.
- Events created, moved or deleted in Google Calendar show up on Today within a minute.
  Deleting a synced event dismisses its task (you get a notification).
- The Calendar event ID is stored on each task, so a task can never create a second event.
- Overlaps with existing events are reported when syncing and checked before the assistant schedules.
- Only the Today page uses Calendar; Overview and This Week are unchanged.

### Multiple Gmail accounts

- Connect several Google accounts, each with its own encrypted read-only token.
- Label accounts (School, Personal, Work, or your own) and switch from the account menu.
- The selected account (or **All accounts**) controls which Gmail is scanned, searched and shown in Scan History.
- Tasks from every account still appear everywhere in the app.

### AI assistant

- Searches and reads your email (read-only) to pull out assignments, deadlines and details.
- Creates, updates and deletes Calendar events when asked, checking for conflicts first.
- Safety: events are only changed when your message asks for it; update/delete are blocked in a
  turn that read email; events never invite anyone.

### Settings

- Timezone and workday hours.
- Default scan duration from 1 to 365 days.
- Scan-completion notification preference.
- VIP sender rules.
- Ignored sender rules.

## Main Routes

### Frontend

- `/` - Today dashboard.
- `/week` - Weekly agenda.
- `/scans` - Scan history, rerun/delete controls, and notification history.
- `/settings` - Workday settings and privacy dashboard.

### Backend

- `GET /api/auth/google` - Start Google OAuth.
- `GET /api/auth/google/callback` - Complete OAuth and redirect to the app.
- `GET /api/auth/me` - Current user.
- `PATCH /api/auth/settings` - Update user settings.
- `GET /api/auth/data-summary` - Privacy summary.
- `DELETE /api/auth/imported-data` - Delete imported data only.
- `DELETE /api/auth/account` - Delete the account and all user data.
- `POST /api/gmail/sync` - Queue a background scan.
- `GET /api/gmail/scans` - List the current user's scans.
- `GET /api/gmail/scans/{scan_id}` - Read scan status/progress.
- `POST /api/gmail/scans/{scan_id}/rerun` - Queue a new run from an old run.
- `DELETE /api/gmail/scans/{scan_id}` - Delete one scan record.
- `GET /api/gmail/notifications` - List persisted notifications.
- `POST /api/gmail/notifications/read-all` - Mark notifications read.
- `GET /api/tasks` - List and filter tasks.
- `GET /api/tasks/{task_id}` - Read task details and source emails.
- `PATCH /api/tasks/{task_id}` - Edit task fields.
- `GET /api/calendar/status`, `POST /api/calendar/connect`, `POST /api/calendar/sync`,
  `GET /api/calendar/events`, `DELETE /api/calendar/disconnect` - Google Calendar.
- `GET /api/gmail/accounts`, `POST /api/gmail/accounts/connect`, `PUT /api/gmail/accounts/selected`,
  `PATCH|DELETE /api/gmail/accounts/{id}` - Multiple Gmail accounts.

## Local Development

Start the backend:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --reload-dir app --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

The backend performs a lightweight SQLite schema upgrade at startup for the
new settings, task, and scan-progress columns. Production deployments should
replace this with Alembic migrations and a durable worker such as Celery or a
managed queue.
