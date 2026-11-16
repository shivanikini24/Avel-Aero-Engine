import argparse
import shutil
import sys
from pathlib import Path

from engine import Workflow, Step
from tools import MockTools, DEFAULT_REQUEST


def build(args):
    failures = {} if args.no_fail else {}
    for spec in (args.fail or ([] if args.no_fail else ["check_availability:1"])):
        name, _, n = spec.partition(":")
        failures[name] = int(n or 1)
    t = MockTools(failures)
    steps = [
        Step("check_availability", "Check availability",
             lambda c: t.check_availability(c["request"]), "Aircraft availability received"),
        Step("prepare_quote", "Prepare quote",
             lambda c: t.prepare_quote(c["request"], c["check_availability"]), "Draft prepared"),
        Step("human_approval", "Wait for human approval", gate=True),
        Step("send_quote", "Send quote (mock)",
             lambda c: t.send_quote(c["prepare_quote"], c["request_id"]),
             "Mock send completed", requires_approval=True),
    ]
    return Workflow(args.id, DEFAULT_REQUEST, steps,
                    state_dir=args.state_dir, backoff=args.backoff)


def main():
    p = argparse.ArgumentParser(description="Charter quote workflow engine (mocked)")
    p.add_argument("command", choices=["run", "approve", "reject", "status"])
    p.add_argument("--id", default="REQ-1042")
    p.add_argument("--state-dir", default=".state")
    p.add_argument("--fail", action="append", metavar="TOOL:N",
                   help="make TOOL fail N times (default: check_availability:1)")
    p.add_argument("--no-fail", action="store_true", help="disable simulated failures")
    p.add_argument("--auto-approve", action="store_true", help="approve automatically (demo)")
    p.add_argument("--fresh", action="store_true", help="discard saved state first")
    p.add_argument("--backoff", type=float, default=0.5)
    args = p.parse_args()

    if args.fresh:
        shutil.rmtree(args.state_dir, ignore_errors=True)
    wf = build(args)

    if args.command == "run":
        wf.run()
        if args.auto_approve and wf.state["status"] == "PAUSED":
            wf.approve(by="auto")
            wf.run()
    elif args.command in ("approve", "reject"):
        getattr(wf, args.command)()
        wf.run()
    else:
        s = wf.state
        print(f"{s['request_id']}: {s['status']} (next step index {s['next_step']})")
        for h in s["history"]:
            print(f"  {h['ts']}  [{h['tag']}] {h['msg']}")
    return 0 if wf.state["status"] != "FAILED" else 1


if __name__ == "__main__":
    sys.exit(main())
