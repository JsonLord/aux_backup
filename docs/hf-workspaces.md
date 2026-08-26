# Hugging Face native login and workspaces

## Identity flow

1. The Space enables native OAuth in the README metadata and renders
   `gr.LoginButton`.
2. Gradio injects the verified `OAuthProfile` and `OAuthToken` into each migrated
   callback. Tokens are not stored in a component or browser-visible `gr.State`.
3. The profile supplies the initial workspace selector. IDs are namespaced as
   `hf:user:<sub>` and `hf:org:<sub>`; organizations with unresolved HF security
   restrictions are excluded.
4. Each callback creates request-scoped HTTP clients and forwards the OAuth access
   token plus the selected workspace. The selection is not authority by itself.
5. With `AUTH_MODE=hf_token`, each API calls the HF OAuth userinfo endpoint, rebuilds
   the allowed workspace set, and rejects a forged or stale selection.
6. `/v1/me` returns the verified user, current workspace list, roles, and selected
   workspace for UI refresh.

## Deployment configuration

Configure the external control plane and persona runtime with:

```text
AUTH_MODE=hf_token
HF_OIDC_USERINFO_URL=https://huggingface.co/oauth/userinfo
```

`AUTH_MODE=local` trusts development headers and must not be used for an internet
deployment. The Space itself receives OAuth client configuration from HF.

## Authorization and revocation

- Personal workspaces map to `owner`.
- Organization `roleInOrg` values are persisted. `owner`, `admin`, `write`, and
  `contributor` can mutate; other roles are read-only.
- Every verified request refreshes the user's directory record, marks old HF
  memberships inactive, and reactivates only memberships returned by current HF
  userinfo.
- Service credentials remain separately scoped and never derive authority from user
  headers.

## Database defense in depth

Migration `0004_workspace_rls` enables and forces PostgreSQL row-level security for
sessions, jobs, artifacts, and personas. API/persona connections use the non-superuser
`aux_app` role and set `app.workspace_id` from verified request context. Celery uses a
separate `BYPASSRLS` worker role because it resolves persisted job IDs without an end
user request.

For an existing development PostgreSQL volume, recreate it or provision the roles in
`infrastructure/postgres/init.sql` before upgrading; Docker init scripts only run on a
new database volume.
