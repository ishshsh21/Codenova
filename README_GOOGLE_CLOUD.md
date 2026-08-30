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
