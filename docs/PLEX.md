# Plex sign-in

Dewarr can offer **Sign in with Plex** next to local passwords. It stays off until an administrator turns it on. This is separate from [OpenID Connect](OIDC.md). A home can use either, or both.

Plex sign-in is for people who already have an account on one Plex server, including accounts invited with Wizarr. Each person gets their own Dewarr session, so a request stays attached to that person. Dewarr does not read the Plex library.

Create the first Dewarr administrator in the browser before enabling Plex. Then open **Settings → Users & access**.

`PUBLIC_URL` must be the exact address in the browser, including `https://` when you use TLS. Plex sends the browser back to:

`https://books.example.com/api/auth/plex/callback`

## Link the household server

1. Choose **Link a Plex server** and approve Dewarr in Plex.
2. Select the server your household uses.
3. Turn on **Enable Plex sign-in**.
4. Turn on **Create accounts on first sign-in** when someone who can access that server should get a Dewarr account the first time they sign in. New accounts are members or viewers, never administrators.
5. Save.

People who can no longer access that server cannot sign in with Plex. Turning the setting off stops Plex sign-in and leaves the Dewarr accounts in place. An account created only through Plex has no local password. The first administrator keeps signing in with theirs.

Plex managed users who cannot approve a normal Plex sign-in are not supported. The Plex token from the approval is used once to check server access and is not stored.
