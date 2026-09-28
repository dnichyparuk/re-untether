# Antigravity `--output-format json` cheatsheet

`agy -p "<prompt>" --output-format json` emits a **single JSON object** (not JSONL) on stdout at
completion. Originally verified on agy 1.0.16; re-verified live on agy 1.2.12 (2026-09), including
failure envelopes (see below) — those were previously unconfirmed.

## Result envelope

```json
{
  "conversation_id": "c0d91872-52f3-4ff8-bc71-965b7a264c66",
  "status": "SUCCESS",
  "response": "OK\n",
  "duration_seconds": 1.24537189,
  "num_turns": 1,
  "usage": {
    "input_tokens": 16795,
    "output_tokens": 6,
    "thinking_tokens": 0,
    "cache_read_tokens": 0,
    "total_tokens": 16801
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `conversation_id` | string (UUID) | stable across resume; the resume token value; empty string on some failure envelopes (e.g. invalid `--model`) |
| `status` | string | `SUCCESS` or `ERROR` (both confirmed live on 1.2.12 — see "Failure envelopes" below) |
| `response` | string | the assistant's answer text (may end with `\n`); can be empty (no output yet) or partial (interrupted/timed-out mid-turn) |
| `duration_seconds` | number | wall-clock |
| `num_turns` | number | increments across a resumed conversation |
| `usage.input_tokens` | number | large even for tiny prompts (system prompt + context) |
| `usage.output_tokens` | number | |
| `usage.thinking_tokens` | number | can be > 0 |
| `usage.cache_read_tokens` | number | present in every envelope observed on 1.2.12; **not modeled** by Untether's `AntigravityUsage` schema (`schemas/antigravity.py`) — decodes fine (unknown fields ignored) but this token count is dropped from usage reporting |
| `usage.total_tokens` | number | sum |
| `error` | string | present on `status: "ERROR"` — see below. Real and confirmed, not speculative as an earlier version of this doc stated |

**No `total_cost_usd`** — tokens only.

## Failure envelopes (confirmed live, agy 1.2.12)

Previously "not reproducible during probing." Now confirmed for two cases:

- **Interrupted mid-turn** (Ctrl+C interactively, or SIGTERM on a headless process): exits
  non-zero (observed rc=1). Envelope still emitted, with whatever partial output/usage had
  accumulated:
  ```json
  {"conversation_id":"6e652d38-...","status":"ERROR","response":"partial text so far",
   "error":"interrupted","duration_seconds":360.66,"num_turns":1,
   "usage":{"input_tokens":607510,"output_tokens":26717,"thinking_tokens":18378,
   "cache_read_tokens":3321625,"total_tokens":634227}}
  ```
- **Invalid `--model`**: exits 1, `conversation_id` is an empty string, `response` is empty,
  `error` is a multi-line message naming the bad model and listing every available model:
  ```json
  {"conversation_id":"","status":"ERROR","response":"",
   "error":"invalid model selection (--model \"bogus\" --effort \"\"): model bogus is not recognized as a known model or custom model in settings\nAvailable models:\n  Gemini 3.8 Flash (High)\n  ...",
   "duration_seconds":0,"num_turns":0,"usage":{...all zero...}}
  ```
  This contradicts the older claim (elsewhere in this doc set) that agy "silently ignores an
  invalid `--model`" — that was true before agy 1.1.2, which changed it to hard-fail.
- **`--print-timeout` expiry** is *not* a failure envelope — it exits 0 with `status: "SUCCESS"`
  (see `runner.md` → "Known limitations" → "Timeout expiry returns a partial result, exit 0").
- A model/agent API error mid-turn (as opposed to interrupt or timeout) is documented upstream
  (agy 1.2.6+ changelog) to exit **3** with a structured `AGY_ERROR: {...}` stderr line; not
  reproduced live during this re-verification.

## Resume

Reusing a captured `conversation_id`:

```
agy -p "<follow-up>" --conversation c0d91872-... --output-format json
→ {"conversation_id":"c0d91872-...","status":"SUCCESS","response":"...","num_turns":2,"usage":{...}}
```

`num_turns` increments and prior context is restored.

## Notes

- Output is a single physical line (newlines inside `response` are `\n`-escaped). The base line
  reader caps at 10 MB per line.
- On a non-TTY pipe, agy (confirmed 1.0.16 through 1.2.12, Linux/WSL) produces output normally —
  no PTY required. (The CHANGELOG's non-TTY discard fix was Windows-specific; re-verify on other
  platforms.)
- `--output-format` was **omitted from `agy --help`** in 1.0.16; as of 1.2.12 it is listed
  (`Output format for print mode (text, json, stream-json) (default text)`).
- Failure envelopes (`status: "ERROR"`) are now confirmed — see "Failure envelopes" above.
