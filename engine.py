"""Tiny durable workflow engine: ordered steps, retries, approval gate, history."""
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

TERMINAL = {"COMPLETE", "REJECTED"}


class TransientError(Exception):
    """Retryable failure (timeouts, 5xx, rate limits)."""


class PermanentError(Exception):
    """Non-retryable failure (bad input, nothing available)."""


class StepFailed(Exception):
    pass


@dataclass
class Step:
    name: str                       # key under which the result is stored in context
    label: str                      # shown in the [RUNNING] line
    fn: Optional[Callable] = None   # fn(context) -> result dict
    success_msg: str = "Done"
    max_attempts: int = 3
    gate: bool = False              # human-approval checkpoint (no fn)
    requires_approval: bool = False  # engine refuses to run this unless approved


class Workflow:
    def __init__(self, request_id, request, steps, state_dir=".state",
                 backoff=0.5, sleep=time.sleep, out=print):
        self.steps, self.backoff, self.sleep, self.out = steps, backoff, sleep, out
        self.path = Path(state_dir) / f"{request_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {
                "request_id": request_id, "status": "NEW", "next_step": 0,
                "approval": None, "history": [],
                "context": {"request_id": request_id, "request": request},
            }

    # ---- persistence / history -------------------------------------------------
    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written file

    def log(self, tag, msg):
        self.state["history"].append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tag": tag, "msg": msg})
        self._save()
        self.out(f"{f'[{tag}]':<12}{msg}")

    # ---- execution -------------------------------------------------------------
    def run(self):
        s = self.state
        if s["status"] in TERMINAL:
            self.log("INFO", f"Workflow already {s['status']}; nothing to do")
            return s
        if s["status"] == "NEW":
            self.log("START", f"Workflow {s['request_id']}")
        else:
            self.log("RESUME", f"Resuming at step {s['next_step'] + 1}: "
                               f"{self.steps[s['next_step']].label}")
        s["status"] = "RUNNING"

        while s["next_step"] < len(self.steps):
            step = self.steps[s["next_step"]]

            if step.gate:
                if s["approval"] is None:
                    s["status"] = "PAUSED"
                    self.log("PAUSED", "Waiting for human approval")
                    return s
                if s["approval"] == "rejected":
                    s["status"] = "REJECTED"
                    self.log("REJECTED", "Draft rejected; nothing was sent")
                    return s
                s["next_step"] += 1
                self._save()
                continue

            # Invariant enforced by the engine, not by step authors.
            if step.requires_approval and s["approval"] != "approved":
                raise RuntimeError(f"'{step.name}' blocked: no approval on record")

            self.log("RUNNING", step.label)
            try:
                result = self._attempt(step)
            except StepFailed as e:
                s["status"] = "FAILED"
                self.log("HALTED", f"{e} - fix and re-run to resume from this step")
                return s
            s["context"][step.name] = result
            s["next_step"] += 1
            self.log("SUCCESS", step.success_msg)

        s["status"] = "COMPLETE"
        self.log("COMPLETE", "Workflow finished")
        return s

    def _attempt(self, step):
        for attempt in range(1, step.max_attempts + 1):
            if attempt > 1:
                self.log("RETRY", f"Attempt {attempt}")
                self.sleep(self.backoff * 2 ** (attempt - 2))  # 0.5s, 1s, 2s...
            try:
                return step.fn(self.state["context"])
            except TransientError as e:
                self.log("FAILED", str(e))
            except Exception as e:  # permanent: retrying won't help
                self.log("FAILED", f"{type(e).__name__}: {e} (not retryable)")
                raise StepFailed(f"'{step.name}' failed permanently")
        raise StepFailed(f"'{step.name}' failed after {step.max_attempts} attempts")

    # ---- human decisions -------------------------------------------------------
    def _decide(self, decision, by, tag, msg):
        if self.state["status"] != "PAUSED":
            raise RuntimeError(f"Cannot {decision}: workflow is {self.state['status']}, not PAUSED")
        self.state["approval"] = decision
        self.log(tag, f"{msg} (by {by})")

    def approve(self, by="cli"):
        self._decide("approved", by, "APPROVED", "Human approves draft")

    def reject(self, by="cli"):
        self._decide("rejected", by, "REJECTED", "Human rejects draft")
