# Domain language

- **Activity**: metadata about a turn, including tool names, arguments, and
  lifecycle events, displayed in terminal scrollback or written to an audit log.
- **Activity redaction**: the shared policy for removing recognized sensitive
  values from activity before output. `activity.py` owns this policy;
  the terminal and JSONL adapters call its `sanitize_activity` interface.
- **Turn**: one user request and its agent execution in a conversation thread.
- **Audit log**: a private JSONL file recording lifecycle metadata for one turn.
- **Browser session**: the browser, page, and owner thread shared by browser
  actions during one application lifetime. A conversation reset retains it.
- **Persistent memory**: local guidance and reusable insights exposed to the
  agent beneath `/memories/` and refreshed in the active conversation after a turn.

## Activity redaction seam

The activity module owns recursive key redaction, URL filtering, recognized
string-secret masking, and value length limits. This gives privacy changes
locality and gives both output adapters leverage from the same implementation.
The module has no model, browser, filesystem, or configuration dependencies.

Terminal control-character handling and rendering belong to the terminal
adapter. File permissions, persistence, and event metadata belong to the audit
adapter. Verbose tool results and assistant responses are outside the argument
redaction interface; arbitrary secrets in free text cannot be reliably detected.

## Turn execution seam

`turn.py` owns stream interpretation, tool-call deduplication, audit lifecycle,
memory refresh, and completion, failure, or cancellation. Its `run_turn`
interface emits plain `TurnUpdate` values and returns a `TurnOutcome`; the
terminal adapter renders these values and uses the outcome as the process exit
code for `--once`. This gives lifecycle ordering locality and lets a replay
adapter exercise the same interface as the CLI without Rich.

Memory refresh happens before the final completion event. Refresh failure is a
visible warning; execution failure and cancellation remain distinct outcomes.
The terminal adapter escapes untrusted activity and retains complete scrollback.

## Browser session seam

`browser.py` owns lazy startup, serialized page actions, partial-start rollback,
and cleanup. `BrowserSession.run` keeps page objects inside owner-thread actions.
`close` allows reopening; `shutdown` rejects new actions, waits for accepted
actions, releases resources, and joins the worker. The tool adapter in `tools.py`
binds to a session instead of coordinating process-global browser objects.

`agent_session` owns the application lifetime and always shuts down the browser,
including when agent construction fails. Importing the agent module does not
construct a model, initialize memory files, or launch a browser. Tests replace
Playwright at its factory seam; no alternate production browser adapter is needed.

## Persistent memory seam

`MemorySetup` owns the `/memories/` route, source names, and translation from local
filesystem paths to agent-visible keys. Both backend routing and refresh use this
owner. Its `load_contents` interface gives callers fresh contents without
requiring storage-path knowledge. The filesystem adapter is tested against real
temporary files, including reads through the composite backend.

The agent may write `insights.md`; guidance and skill files remain protected by
the existing filesystem permissions. Missing memory files are skipped, while
other read failures are reported.
