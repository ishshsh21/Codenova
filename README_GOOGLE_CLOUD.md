# Google Cloud Configuration

## Current Gmail-only application

The chatbot uses Google's hosted Gmail MCP server for read-only thread search
and retrieval. Existing Gmail OAuth setup is sufficient after you enable the
Gmail MCP API in the same Google Cloud project.

Required APIs:

- Gmail API
- Gmail MCP API (`gmailmcp.googleapis.com`)

Required OAuth scope:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Required authorized redirect URI for local development:

```text
http://localhost:8000/api/auth/google/callback
```

The value must exactly match `GOOGLE_REDIRECT_URI` in `backend/.env`.

Required local environment values:

```env
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GMAIL_MCP_ENDPOINT=https://gmailmcp.googleapis.com/mcp/v1
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
FRONTEND_URL=http://localhost:5173
```

While the OAuth consent screen is in Testing mode, every account that signs
in must be listed under Test users. The unverified-app warning is expected for
a development app.

## Gmail MCP setup

1. In **Google Cloud Console → APIs & Services → Library**, enable **Gmail API**
   and **Gmail MCP API**.
2. In **Google Auth Platform → Data Access**, retain
   `https://www.googleapis.com/auth/gmail.readonly`. This integration exposes
   only read-only MCP tools, so do not add `gmail.compose` or `gmail.modify`.
3. The Gmail MCP server is currently a Google Workspace Developer Preview.
   Enroll the project/account in the preview if the Gmail MCP API is not
   available in the API Library.
4. For an External OAuth app in Testing, add each user under **Audience → Test
   users**. For production use of the restricted `gmail.readonly` scope,
   complete Google's OAuth verification and applicable security assessment.

The backend sends the existing user OAuth access token to the official endpoint
`https://gmailmcp.googleapis.com/mcp/v1`; no separate MCP client secret or
third-party Gmail MCP server is required.

## Google Calendar sync (Today page)

"Connect Calendar" on the Today page asks for a separate, narrower grant than Gmail sign-in.

1. In **APIs & Services → Library**, enable **Google Calendar API** in the same project.
2. In **Google Auth Platform → Data Access**, add the scope
   `https://www.googleapis.com/auth/calendar.events` (view and edit events).
3. No new redirect URI is needed: Calendar and extra Gmail accounts reuse
   `GOOGLE_REDIRECT_URI`.
4. While the consent screen is in Testing, the Google account you connect must be a test user.

The calendar account can differ from the Gmail sign-in account (Google lets you pick one).
Disconnecting stops syncing but leaves the events already in Google Calendar.

## Adding more Gmail accounts

"Add Gmail account" in the account menu runs the same read-only `gmail.readonly` consent for
another Google account, with its own refresh token. While in Testing, each added account
must also be listed under **Audience → Test users**.

## AI assistant: Calendar and Gmail tools

The assistant can create, move and delete calendar events and search/read email, but it needs
`GEMINI_API_KEY` in `backend/.env` (without it the assistant answers only the built-in task
questions). Email search goes through the Gmail MCP server; if that API isn't enabled yet it
falls back to the Gmail API with the same read-only scope.

## Gmail API quota ("rateLimitExceeded")

Gmail limits each user to 6,000 quota units per minute, and downloading one message
(`messages.get`) costs 20 units, so about 300 messages per minute. A scan of 150 emails uses
roughly half of that. The app:

- downloads only emails it hasn't imported yet, so repeating a scan is cheap;
- backs off and retries when Gmail says the limit was hit;
- if the limit still holds, keeps what it fetched and shows "Scan paused by Gmail rate limit";
  wait about a minute and use **Rerun scan** to continue.

Your project's actual limit is shown under **APIs & Services → Gmail API → Quotas**. If you hit
it often, lower `MAX_MESSAGES_PER_SYNC` (default 150) or `SYNC_WORKER_COUNT` (default 8) in
`backend/.env`. Other Gmail reads, such as the assistant searching your email, count against the
same budget.

## Features that require no Google Cloud changes

The following are application/database features and do not need new Google
permissions:

- Scan history and reruns.
- Scan deletion.
- Background progress tracking.
- Notifications.
- Task filtering, editing, notes, and snoozing.
- VIP and ignored sender rules.
- Settings and privacy dashboard.
- Imported-data deletion and account deletion.

## Production deployment checklist

- Replace localhost redirect URIs with the HTTPS backend callback URI.
- Add the HTTPS frontend origin to `FRONTEND_URL` and CORS configuration.
- Use HTTPS and set the session cookie `secure=True`.
- Move OAuth state/PKCE storage from process memory to shared durable storage.
- Keep the app in Testing only for controlled users; complete verification for
  broad external use of sensitive Gmail scopes.
- Publish a privacy policy and terms of service before production review.
- Use a real database migration system instead of the local SQLite upgrader.
- Use a durable background worker instead of in-process FastAPI background
  tasks.
