# Gmail OAuth Troubleshooting

## `invalid_grant: Token has been expired or revoked`

This error occurs when the Gmail OAuth refresh token becomes invalid. The code *does* attempt to auto-refresh tokens, but refresh tokens themselves can become invalid.

### Common Causes

1. **OAuth App in "Testing" Mode (Most Common)**
   - If your Google Cloud project's OAuth consent screen is in "Testing" status, refresh tokens expire after **7 days**
   - This is the most common cause during development
   - **Fix:** Change OAuth consent screen from "Testing" to "Production" in Google Cloud Console

2. **User Revoked Access**
   - User removed the app from their Google Account settings
   - Immediately invalidates all tokens
   - **Fix:** Re-run OAuth flow to get new tokens

3. **Password Change**
   - If the token includes Gmail scopes and the user resets their password, the refresh token is revoked
   - **Fix:** Re-run OAuth flow

4. **Token Inactivity**
   - Refresh tokens unused for **6 consecutive months** are automatically invalidated
   - Should not happen with active email processing
   - **Fix:** Re-run OAuth flow

5. **Token Limit Exceeded**
   - There's a limit of **50 refresh tokens** per user per OAuth client
   - Creating new tokens invalidates oldest ones
   - Can happen if OAuth flow is run many times
   - **Fix:** Re-run OAuth flow (old tokens are already invalid)

6. **Server Time Sync Issues**
   - Server time not synced with Google servers
   - **Fix:** Use NTP to sync server time

### How to Fix

#### Option 1: Move to Production (Recommended for permanent fix)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **APIs & Services > OAuth consent screen**
3. Click **Publish App** to move from "Testing" to "Production"
4. If app is for personal use only, you don't need verification - just publish

#### Option 2: Regenerate OAuth Token

1. Run the OAuth flow locally:
   ```bash
   python setup_gmail_push.py
   ```

2. This will open a browser for authentication

3. Update Secret Manager with the new token:
   ```bash
   gcloud secrets versions add gmail-oauth-token --data-file=data/gmail_token.json
   ```

### Current Architecture

The Cloud Function stores OAuth credentials in **Secret Manager**:
- Secret name: `gmail-oauth-token`
- Contains: `token`, `refresh_token`, `client_id`, `client_secret`, `token_uri`, `scopes`

The code in `main.py` (`get_gmail_service()`) attempts to refresh expired tokens:
```python
if not creds.valid or creds.expired:
    creds.refresh(Request())
```

However, this only refreshes the **access token** using the refresh token. If the refresh token itself is invalid (revoked, expired in Testing mode, etc.), the refresh fails with `invalid_grant`.

### Known Issue: Token Not Saved After Refresh

The Cloud Function refreshes tokens in memory but does **not** update Secret Manager with the new access token. This is fine for normal operation since the refresh token can get a new access token each time, but it means:
- Every cold start requires a token refresh call to Google
- Slightly higher latency on first request after cold start

This could be improved by updating Secret Manager after successful refresh, but it's not critical as long as the refresh token remains valid.

### References

- [Google OAuth invalid_grant Explained](https://nango.dev/blog/google-oauth-invalid-grant-token-has-been-expired-or-revoked)
- [Google OAuth Nightmare and How to Fix It](https://blog.timekit.io/google-oauth-invalid-grant-nightmare-and-how-to-fix-it-9f4efaf1da35)
