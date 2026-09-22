# OpenID Connect

Dewarr can sign people in with one OpenID Connect provider. Authentik, Pocket ID, and Authelia all use this same setup. Local usernames and passwords stay available, including the first administrator account.

Create that first account in the browser before enabling the provider. Then open **Settings → Users & access**.

`PUBLIC_URL` must be the exact address in the browser, including `https://` when you use TLS. The redirect URL shown on the settings page is:

`https://books.example.com/api/auth/oidc/callback`

Copy it into the provider. Dewarr uses authorization code with PKCE (`S256`) and `client_secret_basic`. Correcting the issuer path keeps existing links when the scheme, host, and port stay the same. A different scheme, host, or port removes those links, so a reused subject cannot sign in as the old account.

## Authentik

1. Create an application and choose the **OAuth2/OpenID Connect** provider. This is not the proxy provider.
2. Note the client ID and client secret.
3. Add the Dewarr redirect URL as a strict authorization redirect URI.
4. In Dewarr, paste the issuer URL (`https://authentik.example/application/o/<slug>`), choose **Discover endpoints**, enter the client ID and secret, and save.
5. Leave **Match existing accounts** on username or verified email if these people already have Dewarr accounts. Verified email matches only when the provider sets `email_verified` to true. Username matching does not attach an administrator account. Turn on **Create accounts on first sign-in** only when the provider should add new readers.
6. Optional: set the group claim to `groups` and enter the Authentik group names that should become administrators, members, or viewers. Leave **Group scope** empty unless Authentik releases that claim only when Dewarr requests a scope. A scope the provider does not offer rejects every provider sign-in.

A user's email must not be marked unverified. Authentik does that until the address is confirmed.

## Pocket ID

1. Create an OIDC client named Dewarr.
2. Set the callback URL to the Dewarr redirect URL.
3. Copy the client ID and client secret.
4. In Dewarr, paste the Pocket ID address (`https://id.example.com`) as the issuer, choose **Discover endpoints**, and save the client ID and secret.

Pocket ID puts group names in the `groups` claim. Set the group claim and the group scope to `groups`, and enter the Pocket ID group names in the role fields.

## Authelia

Add a confidential client that requires PKCE. Replace the secret with a hashed Authelia secret and the redirect with your Dewarr address:

```yaml
identity_providers:
  oidc:
    clients:
      - client_id: "dewarr"
        client_name: "Dewarr"
        client_secret: "$pbkdf2-sha512$..."
        public: false
        require_pkce: true
        pkce_challenge_method: "S256"
        redirect_uris:
          - "https://books.example.com/api/auth/oidc/callback"
        scopes:
          - "openid"
          - "profile"
          - "email"
          - "groups"
        response_types:
          - "code"
        grant_types:
          - "authorization_code"
        token_endpoint_auth_method: "client_secret_basic"
```

In Dewarr, the issuer is the Authelia address (`https://auth.example.com`). Discover fills the authorize, token, userinfo, and JWKS URLs. Set the group claim and the group scope to `groups`.

## Roles

New provider accounts are members unless a group mapping says otherwise. They cannot run list automation until an administrator allows it. Group mapping does not change the role of an account that still has a local password, and it will not remove the last active administrator. Signing out of Dewarr ends the Dewarr session only; the identity provider session can remain.

People created by the provider have no Dewarr password. Disabling the provider blocks their sign-in until you turn it back on or give them a local account.
