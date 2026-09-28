# Antigravity → Untether event mapping

`agy --output-format json` returns one terminal result envelope, which the runner translates into
the standard 3-event contract in a single `translate()` call: one `StartedEvent` followed by one
`CompletedEvent` (there are no intermediate `ActionEvent`s).

## Mapping

| Untether event / field | Source in the agy envelope |
|------------------------|----------------------------|
| `StartedEvent.resume` | `ResumeToken(engine="antigravity", value=conversation_id)` |
| `StartedEvent.title` | configured model name (or `"antigravity"`) |
| `StartedEvent.meta.model` | configured / `/model` override (envelope has no model echo) |
| `StartedEvent.meta.permissionMode` | `"full access"` (auto-approve) and/or `"sandbox"`, joined by `" · "` |
| `CompletedEvent.ok` | `status == "SUCCESS"` |
| `CompletedEvent.answer` | `response` |
| `CompletedEvent.resume` | same `ResumeToken` as Started |
| `CompletedEvent.usage.usage.{input,output,thinking}_tokens` | `usage.*` |
| `CompletedEvent.usage.duration_ms` | `duration_seconds * 1000` |
| `CompletedEvent.usage.num_turns` | `num_turns` |
| `CompletedEvent.error` | `error` or `"agy status: <status>"` when not SUCCESS |

## No `ActionEvent`s

Because the envelope is terminal-only, no tool/file/command progress is available — the progress
message stays "working…" until the final answer. This is the primary difference from streaming
engines like Gemini (`stream-json`).

## Terminal fallbacks

| Condition | Runner behaviour |
|-----------|------------------|
| Non-zero exit code, **no** envelope decoded | `process_error_events` → note + `CompletedEvent(ok=False)` with rc label + stderr excerpt |
| Non-zero exit code, envelope **was** decoded (`did_emit_completed`) | `process_error_events` is skipped — the `CompletedEvent` already emitted from `translate()` (with the envelope's real `error` text) stands. Confirmed live (agy 1.2.12) for interrupted runs (rc=1, `error: "interrupted"`) and invalid `--model` (rc=1, `error` lists available models) — both cases still emit a usable envelope, so this path handles them correctly today |
| No envelope on stdout | `stream_end_events` → `CompletedEvent(ok=False, error="agy produced no result envelope")` |
| Undecodable JSON line | `decode_error_events` drops the line (logs `jsonl.msgspec.invalid`) |
| `--print-timeout` expiry | **Not** a terminal-fallback case — agy exits 0 with `status: "SUCCESS"`, so it's handled by the normal `translate()` success path with `ok=True`, even though the run was cut short. See `runner.md` → "Known limitations". |
| rc=3 (`AGY_ERROR`, model/agent API failure) | Documented upstream since agy 1.2.6 but not reproduced live; unconfirmed whether an envelope is always decoded in this case. If not, falls into the first row above with no rc=3-specific handling. |
