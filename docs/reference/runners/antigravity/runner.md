# Antigravity runner (`agy`)

The Antigravity runner integrates Google's [Antigravity CLI](https://antigravity.google/docs/cli-overview)
(`agy`) as a **non-interactive, structured-result** engine. Originally verified against `agy`
1.0.16; re-verified live against `agy` 1.2.12 (2026-09) — see "Known limitations" below for what
changed between those versions. `agy` ships frequent releases; re-check `agy --help` and
`agy changelog` against this doc before trusting version-specific claims.

## Capability tier

`agy -p "<prompt>" --output-format json` returns a **single JSON result envelope** at
completion — not a streaming event feed. The runner therefore emits:

- a real `ResumeToken` (from `conversation_id`),
- the answer (`response`),
- ok/error (from `status`),
- token usage (`usage`).

It does **not** produce live `ActionEvent` progress (no intermediate tool/file events),
interactive approval, plan mode, AskUserQuestion, or USD cost (the envelope carries tokens
only). agy has no bidirectional control channel, so approval is decided at spawn time.

## Prerequisites

- `agy` on `PATH` — `curl -fsSL https://antigravity.google/cli/install.sh | bash`.
- **Pre-authenticated on the host.** agy authenticates via the OS keyring → Google OAuth;
  there is no API-key environment variable. Because Untether runs headless, complete an
  interactive `agy` login once per host so the daemon inherits the saved session.

## CLI invocation

`command()` → `agy`. `build_args` (order):

| Arg | When |
|-----|------|
| `-p <sanitized prompt>` | always (prompt is sanitized so a leading `-` isn't parsed as a flag) |
| `--output-format json` | always — yields the structured envelope |
| `--model <name>` | `[antigravity] model` or per-run `/model` override; full display name, e.g. `"Gemini 3.1 Pro (High)"` |
| `--continue` | `/continue` — resumes the machine-most-recent conversation |
| `--conversation <id>` | resume a specific conversation (id from a prior envelope) |
| `--sandbox` | `[antigravity] sandbox = true` |
| `--dangerously-skip-permissions` | `[antigravity] auto_approve = true` (default) — headless auto-approve |
| `--print-timeout <dur>` | `[antigravity] print_timeout` (Untether default `15m`, overrides agy's own default — unlimited as of agy 1.2.6, see "Known limitations") |
| `--add-dir <path>` | the resolved run cwd (project dir) is auto-added first, then one per `[antigravity] add_dirs` |

The prompt is passed on argv; stdin is closed (`stdin_payload()` → `None`). No PTY is used.
Environment is allowlist-filtered (`utils/env_policy.py`, #198) — the subprocess does not
inherit the full daemon environment.

### Working directory

`agy` has no `--cwd`/`--workspace`/positional working-directory flag; its only directory
lever is `--add-dir` ("Add a directory to the workspace, repeatable"). Run headlessly (`-p`),
`agy` does **not** reliably adopt its inherited process cwd as the workspace — it falls back to
`~/.gemini/antigravity-cli/scratch`, so files land outside the project. To pin `agy` to the
project, `build_args` injects the resolved run cwd (`get_run_base_dir()` — the
`[projects.<alias>].path` for the active topic) as the **first** `--add-dir`, ahead of any
configured `add_dirs`; duplicates are dropped. When no run cwd is set (a run path that never
called `set_run_base_dir`), only the configured `add_dirs` are passed.

Caveat: if a project's `path` sits under a **dot-prefixed** ancestor directory (e.g. a
`[new_project] root` like `~/.untether/projects`), `agy` rejects both the cwd and the
`--add-dir` and falls back to scratch anyway — see upstream
[antigravity-cli#20](https://github.com/google-antigravity/antigravity-cli/issues/20). Keep
`[new_project] root` / `[clone] root` non-dotted.

## Configuration (`[antigravity]`)

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `model` | string | none | `--model` |
| `sandbox` | bool | `false` | `--sandbox` |
| `auto_approve` | bool | `true` | `--dangerously-skip-permissions` |
| `print_timeout` | string | `15m` | `--print-timeout` (overrides agy's own default — unlimited as of agy 1.2.6) |
| `add_dirs` | list[string] | `[]` | extra `--add-dir` entries (the run cwd / project dir is auto-added first — see "Working directory") |
| `extra_args` | list[string] | `[]` | appended (Untether-managed flags rejected) |

Reserved flags (rejected in `extra_args`): `-p`, `--print`, `--prompt`, `--output-format`,
`--continue`, `-c`, `--conversation`, `--model`, `--dangerously-skip-permissions`, `--sandbox`.
The last two are derived from the `auto_approve` / `sandbox` config booleans, so allowing them
via `extra_args` could silently contradict the configured permission stance.

## Resume

- `format_resume` renders `` `agy --conversation <id>` ``; replying to a message with that
  footer resumes the conversation (via `AutoRouter`).
- `--continue` resumes the **machine-global** most-recent conversation — potentially the wrong
  chat in a multi-chat deployment. Prefer per-session resume (`--conversation <id>`), which the
  runner emits in every footer.

## Known limitations

- **No live progress** — the envelope is terminal-only, so the Telegram message shows
  "working…" then the final answer. A long healthy run is stdout-silent; tune the `[watchdog]`
  expectations for this engine accordingly. While the run is in flight, the progress bubble's
  meta footer now surfaces a liveness line (e.g. `⏱ 3m / 15m · process alive · CPU active`)
  refreshed on every stall-monitor tick, so a silent agy run still shows a heartbeat signal
  even without interim `ActionEvent`s. This line is cleared before the final message is
  rendered — it never appears on the completed run.
- **agy's own print-timeout default changed (1.2.6) — no longer 5m0s** — through agy 1.2.5,
  a headless run with no `--print-timeout` was killed at a built-in `5m0s`. As of **1.2.6**,
  `agy changelog` states the default "chang[ed] ... from 5 minutes to unlimited so long-running
  agent turns run until the response completes unless `--print-timeout` is passed explicitly";
  `agy --help` on 1.2.12 confirms this (`0 waits until the turn completes (default 0s)`).
  Untether pins `--print-timeout` to `15m` regardless (`--print-timeout 15m`) so long tasks are
  still bounded — that behaviour is unchanged. **But `print_timeout = ""` no longer "restores
  agy's built-in `5m0s`"** as previously documented here: omitting the flag today means *no
  timeout at all*. This is a real, reproduced risk, not theoretical — during live probing
  (2026-09, agy 1.2.12) a trivial one-word prompt run with no `--print-timeout` ran for **6
  minutes and consumed 634k tokens** (`cache_read_tokens: 3,321,625`) before being killed
  manually, versus ~3s/15k tokens on a normal retry. Avoid `print_timeout = ""` unless unbounded
  headless runs are actually intended.
  Untether's stdout-gated liveness watchdog is inert for a stdout-silent agy run, but the
  bridge's event-silence stall monitor (`runner_bridge.py:_stall_monitor`) is **not** —
  since agy emits no interim `ActionEvent`s, the monitor derives its stall threshold from
  the run's resolved `print_timeout` (`AntigravityRunner.expected_silence_budget_s()`) plus
  a 60-second margin, so a healthy run completes before a stall warning fires. Raising
  `[antigravity] print_timeout` (or a project's `print_timeout` override) no longer causes a
  false stall warning — the threshold always tracks whatever timeout is actually in effect.
  **This is no longer unconditionally true as of this fix** — it holds for wrapped runs too
  now, *except* when `runner_bridge.py`'s threshold-priority branches
  (`_has_active_children()` — a live child PID, or `tcp_total` above the 20-connection
  `_TCP_ACTIVE_THRESHOLD`) select the fixed 900s `_STALL_THRESHOLD_SUBAGENT` threshold
  instead of the silent-engine budget derived from `expected_silence_budget_s()`. That
  branch runs ahead of the silent-engine branch in the priority chain, so a wrapped
  Antigravity run that happens to spawn a child process or open enough TCP connections
  still gets the 900s subagent threshold rather than a print-timeout-derived one. This is a
  known, separate limitation, not addressed by this fix — see the discussion on PR #14 for
  context.
  Tune via `[antigravity] print_timeout` (Go duration syntax).
- **Timeout expiry returns a partial result, exit 0** (since 1.1.28, confirmed live on 1.2.12) —
  when `--print-timeout` expires mid-turn, agy prints
  `[agy] print timeout after <dur> with turn in progress; returning partial output` to stderr and
  exits **0** with a `status: "SUCCESS"` envelope (`response` may be empty if the turn hadn't
  produced text yet). An interactive interrupt (Ctrl+C, or SIGTERM sent to a headless process)
  still exits non-zero (observed rc=1) with `status: "ERROR"`, `error: "interrupted"`, and
  whatever partial `response`/`usage` had accumulated.
  **The envelope does not distinguish a timeout-truncated run from a genuine completion** —
  both report `status: "SUCCESS"`. Untether's `translate()` reads `ok = status == "SUCCESS"`, so
  a truncated run is presented to the user as a normal successful completion with a
  possibly-empty answer; only the stderr line signals truncation, and Untether does not
  currently scan stderr on the rc=0 path.
- **Per-project override precedence** — a project's `[projects.<alias>].print_timeout`
  (settable from Telegram via `/printtimeout`) takes precedence over the global
  `[antigravity] print_timeout` default, which in turn takes precedence over agy's own
  built-in default — **unlimited** as of agy 1.2.6, not the `5m0s` this doc previously
  claimed (see "agy's own print-timeout default changed" above). Resolution happens per-run
  via the `EngineRunOptions` ContextVar (the same channel `model` uses) — see
  `AntigravityRunner._resolved_print_timeout()`.
- **No USD cost / budgets** — tokens only. Live envelopes (agy 1.2.12) also include a
  `usage.cache_read_tokens` field that Untether's `AntigravityUsage` schema does not model
  (`schemas/antigravity.py`) — it decodes fine (unknown fields are ignored) but that token
  category is silently dropped from usage reporting.
- **Model footer may misreport, but invalid `--model` no longer fails silently** — the envelope
  still has no `model` field, so the footer always reflects the *configured* model rather than
  what actually ran. However, contrary to the previous claim here, `agy` does **not** silently
  ignore an invalid `--model`: confirmed live on 1.2.12, an unrecognized model name hard-fails
  (exit 1, `status: "ERROR"`, `error` lists the available models) — this was fixed upstream in
  agy 1.1.2 ("hard-failing with a non-zero exit and listing the available models" per
  `agy changelog`). Untether's runner already handles this correctly (the error envelope decodes
  and surfaces via the normal `ok=False` path); only this doc's claim was stale.
- **Model/agent API errors mid-turn can exit 3** — since agy 1.2.6, a turn that fails on a
  model or agent API error (as opposed to a clean timeout or an interrupt) prints a structured
  `AGY_ERROR: {...}` line to stderr and exits **3** (agy 1.2.10 further ensured the JSON output
  in this case still includes the partial response, rather than exiting 0 as earlier versions
  did). This was not reproduced live during re-verification (it requires a genuine backend
  failure) so it's unconfirmed whether the stdout envelope is always present in this case; if it
  ever isn't, `AntigravityRunner.process_error_events()` has no rc=3-specific handling today and
  would fall back to a generic "agy failed (rc=3)" message, losing the `AGY_ERROR` detail.

## Model catalog

`agy models` lists available models. As of agy 1.2.12: `Gemini 3.8 Flash (Low|Medium|High)`,
`Gemini 3.7 Flash (Low|Medium|High)`, `Gemini 3.6 Flash (Low|Medium|High)`,
`Gemini 3.1 Pro (Low|High)`, `Claude Sonnet 4.6 (Thinking)`, `Claude Opus 4.6 (Thinking)`,
`GPT-OSS 120B (Medium)`. The reasoning tier is baked into the model name for these catalog
entries. Separately, agy 1.2.11 added a top-level `--effort` flag
(`low|medium|high|max`, also `/effort` interactively) as another way to select reasoning effort;
`AntigravityRunner` does not pass it today.
