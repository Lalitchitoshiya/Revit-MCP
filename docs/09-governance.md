# 09 — Governance: approvals, audit log, scoped tokens

Thin, working version of three controls requested for the Revit MCP:

1. **Audit log of approvals:** who approved each change, when, how, and what changed.
2. **Per-tool token scopes:** read-only clients vs clients that may change the model.
3. **Token expiry and rotation:** plus revocation and a policy switch for the legacy token.

## Where each control is enforced

```
 Claude client ──stdio──► MCP server (Python) ──loopback socket──► Revit add-in (C#)
   shows the                asks the HUMAN to approve                 verifies token, expiry,
   approval prompt          (MCP elicitation), refuses                revocation, scope on EVERY
                            replays, pre-checks scope                 request; writes the audit log;
                                                                      refuses commit if it can't
```

The add-in is the trust boundary: it is the only component that changes the
model. The MCP server's scope check is a UX fast path; the add-in re-checks.

| Control | MCP server | Add-in |
|---|---|---|
| Human approval of commit/undo | ✅ elicitation prompt raised by the server; the model can't answer it | records it |
| One commit per staged plan | ✅ `PLAN_ALREADY_COMMITTED` | ✅ preview is consumed by its commit |
| Preview tied to the document | – | ✅ preview in doc A can't commit into doc B; undo refuses the wrong doc |
| Token scope per method | pre-check | ✅ `SCOPE_DENIED` (fails closed for unknown methods) |
| Expiry / revocation / rotation | pre-check (expiry) | ✅ re-read from `auth.json` on change, no Revit restart |
| Audit record | reads/verifies | ✅ single writer, hash-chained; commit refused if log not writable |
| Timed-out commit can't run later | – | ✅ cancelled if Revit hadn't started it |

## Approval modes (`REVIT_MCP_APPROVAL`, set per client)

| Mode | Behaviour |
|---|---|
| `elicit` | Server shows an approval prompt (intent + previewed summary + warnings). No prompt-capable client means no commit (`APPROVAL_UNAVAILABLE`). **Use for the demo.** |
| `elicit_or_token` (default) | Prompt when the client supports it; otherwise commit on the confirmation token alone, audited as `human_verified: false`. |
| `token` | Legacy behaviour (token only, never human-verified). |

Claude Code supports the prompt (form-mode elicitation). Claude Desktop support
for local servers is not documented, so demo from Claude Code.

## Tokens

Scopes: `model:read` (all discovery tools, `preview_plan`, `health_check`) and
`model:write` (`commit_plan`, `undo_plan`). The mapping lives in
`addin/src/Auth/Scopes.cs` and `server/revit_mcp/auth.py`; a unit test keeps
them identical.

Installed product: the same commands are `revit-mcp-server.exe auth ...` and
`revit-mcp-server.exe audit ...` (in `%APPDATA%\Autodesk\ApplicationPlugins\RevitMCP.bundle\Contents\Server`).
The ribbon's *Audit log* button shows the latest records and the tamper check. See docs/10-release.md.

```powershell
cd server
.\.venv\Scripts\python.exe -m revit_mcp.auth init                       # creates %LOCALAPPDATA%\RevitMCP\auth.json
.\.venv\Scripts\python.exe -m revit_mcp.auth issue --sub "lalit/claude-code" --scopes model:read,model:write --ttl 8h
.\.venv\Scripts\python.exe -m revit_mcp.auth issue --sub "reviewer/desktop"  --scopes model:read --ttl 30d
.\.venv\Scripts\python.exe -m revit_mcp.auth list                       # keys, issued tokens, validity
.\.venv\Scripts\python.exe -m revit_mcp.auth revoke <jti>
.\.venv\Scripts\python.exe -m revit_mcp.auth rotate --grace 15m         # old tokens keep working 15 min
.\.venv\Scripts\python.exe -m revit_mcp.auth policy --session-token off # only scoped tokens accepted
```

Give a client its token through its MCP config:
`"env": {"REVIT_MCP_TOKEN": "rmcp1....", "REVIT_MCP_APPROVAL": "elicit"}` (or
`REVIT_MCP_TOKEN_FILE`). With no token configured, the server uses the
full-access session token from `session.json`, exactly as before. Nothing
changes until `auth init` is run and a client is given a scoped token.

Format: `rmcp1.<base64url(claims)>.<base64url(HMAC-SHA256)>`; claims are
`kid, sub, scopes, iat, exp, jti`. `auth.json` holds the signing keys and is
restricted to the current Windows user.

## Audit log

`%LOCALAPPDATA%\RevitMCP\audit\audit.jsonl`: one JSON record per line.

* `plan.commit` → `committed` / `refused` / `failed_rolled_back`
* `plan.undo` → `undone` / `refused`
* `auth.denied` → `SCOPE_DENIED` / `TOKEN_EXPIRED` / `TOKEN_REVOKED` / `BAD_TOKEN`

Each record has: UTC time, plan id, intent, previewed summary, op counts,
created element ids + categories (or deleted ids), document title/path,
Revit user name, Windows user, machine, the token identity (`sub`, `jti`,
scopes), and the **approval**: `method` (`elicitation` / `confirmation_token`),
`human_verified`, `approved_by`, `approved_at`, client name, optional comment,
and the exact prompt text the human saw.

Records are hash-chained (`prev_hash` → `hash`), so editing, deleting or
reordering a line is detected:

```powershell
.\.venv\Scripts\python.exe -m revit_mcp.audit tail -n 20
.\.venv\Scripts\python.exe -m revit_mcp.audit verify
```

In chat: ask *"show me the audit log"* (`get_audit_log` tool).

## Demo script (~5 min, Claude Code)

1. `auth init`; issue a **write** token and a **read-only** token.
2. Register two MCP servers in Claude Code: `revit` (write token,
   `REVIT_MCP_APPROVAL=elicit`) and `revit-viewer` (read-only token).
3. *"Run a health check"*: shows `access.scopes` and `approval_mode`.
4. *"Stage a 4 m wall on Level 1, preview it, and commit."* Claude Code shows the
   server's approval prompt. **Decline** first: nothing changes. Ask again,
   **approve** with a comment: the wall appears.
5. Using `revit-viewer`: ask it to commit a change. It refuses with `SCOPE_DENIED`
   (and so does the add-in if the socket is called directly).
6. *"Show me the audit log"*: who approved, when, the comment, the token used,
   the element ids, and `chain_intact: true`.
7. `auth revoke <jti>` of the viewer token. Its next call returns `TOKEN_REVOKED`
   with no restart. `audit verify` still passes; edit a line, and it fails.

## Verification

| Test | Needs Revit | What it proves |
|---|---|---|
| `python -m pytest tests/` | no | token rules, rotation/grace, revocation, scope map parity with C#, audit chain + tamper, approval modes |
| `python -m tools.test_governance` | no | real MCP client ↔ real server ↔ stub add-in: approve/decline/dismiss, replay, read-only refused at server **and** socket, strict vs default mode, audited undo, expired/revoked, tamper |
| `python -m tools.test_governance_live [--commit]` | **yes** | the C# add-in enforces scopes on direct socket calls, audits denials, honours expiry/revocation live, audits commit/undo, refuses replay |

## Honest limits of the thin version

* **Identity is the Windows user** at the client (plus Revit's user name and the
  token's `sub`). There is no SSO, and the approval prompt can't prove *which*
  person sat at the keyboard.
* **Same-user boundary.** Any process running as the same Windows user can read
  `auth.json` / `session.json`. Scopes limit what a *configured client* can do;
  they are not protection against malware running as the user.
* **The add-in trusts the server's approval record.** A holder of a
  `model:write` token who talks to the socket directly can commit without the
  approval prompt. The audit record then shows `approval: null`, so this is
  visible but not prevented. Issue write tokens narrowly.
* The audit log is **local, per machine**: no central shipping, retention policy,
  or signing with a key the user doesn't hold.
* A commit already *running* when its timeout hits is allowed to finish (up to
  10 min) rather than being abandoned mid-transaction.
* The non-warning modal dialog hang (README "open item") is unchanged.
