# Charter Quote Execution Engine

A small, durable workflow engine that runs a four-step charter inquiry flow
(check availability -> prepare quote -> human approval -> send quote). All
services are mocked; nothing is ever sent. Python 3.9+, standard library only.

## Run it

```bash
python3 main.py run --auto-approve          # full demo, incl. a simulated timeout + retry
python3 main.py run                         # runs until PAUSED, then exits
python3 main.py approve                     # (or: reject) resumes from saved state
python3 main.py status                      # state + full history
python3 main.py run --fresh --fail prepare_quote:3   # exhaust retries -> HALTED
python3 -m unittest -v                      # tests
```

`evidence.txt` has captured output of a successful run, a retry, an exhausted-retry
halt, and a resume.

## Architecture

- `engine.py` - `Workflow` runs a list of `Step`s in order. Each step receives a shared
  `context` dict; its result is stored under the step's name, so later steps read earlier
  results (e.g. the quote step reads availability).
- `tools.py` - mocked services with an injectable failure counter ("fail N times, then succeed").
- `main.py` - CLI wiring. `run`, `approve`, `reject`, `status`.
- State (status, next step, context, approval, history) is written as JSON after every
  event, atomically (`os.replace`).

**Failure handling:** `TransientError` (e.g. timeout) is retried up to 3 attempts with
exponential backoff. Any other exception is treated as permanent and fails immediately.
When retries run out the workflow becomes `FAILED`/halted at that step; re-running resumes
at the same step and never repeats completed ones.

## Key decision: approval is enforced by the engine, and state is durable

The approval gate is a first-class step that sets status to `PAUSED` and *returns*, rather
than blocking on `input()`. Because state is persisted, a human can approve minutes or
days later from a different process. On top of that, any step flagged
`requires_approval=True` is refused by the engine unless an approval is on record, so the
"never send without approval" rule doesn't depend on every step author remembering it.

## Limitation

Delivery is at-least-once, not exactly-once: if the process crashed after the (real)
send succeeded but before the result was saved, a resume would call send again. The send
call passes an idempotency key (the request ID) to mitigate this, but my mock does not
actually dedupe. Also: single process, no file locking, so two concurrent runs on the
same request could race.
