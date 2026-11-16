import tempfile
import unittest

from engine import Workflow, Step
from tools import MockTools, DEFAULT_REQUEST


def make(failures=None, tmp=None):
    t = MockTools(failures)
    steps = [
        Step("check_availability", "Check", lambda c: t.check_availability(c["request"])),
        Step("prepare_quote", "Quote", lambda c: t.prepare_quote(c["request"], c["check_availability"])),
        Step("human_approval", "Approval", gate=True),
        Step("send_quote", "Send", lambda c: t.send_quote(c["prepare_quote"], c["request_id"]),
             requires_approval=True),
    ]
    wf = Workflow("T-1", DEFAULT_REQUEST, steps, state_dir=tmp or tempfile.mkdtemp(),
                  sleep=lambda s: None, out=lambda m: None)
    return wf, t


class EngineTests(unittest.TestCase):
    def test_retry_then_success_and_data_flows(self):
        wf, t = make({"check_availability": 1})
        wf.run(); wf.approve(); wf.run()
        self.assertEqual(wf.state["status"], "COMPLETE")
        self.assertEqual(t.calls["check_availability"], 2)
        self.assertIn("MSG-T-1", wf.state["context"]["send_quote"]["message_id"])

    def test_never_sends_before_approval(self):
        wf, t = make()
        wf.run()
        self.assertEqual(wf.state["status"], "PAUSED")
        self.assertEqual(t.calls["send_quote"], 0)

    def test_reject_never_sends(self):
        wf, t = make()
        wf.run(); wf.reject(); wf.run()
        self.assertEqual(wf.state["status"], "REJECTED")
        self.assertEqual(t.calls["send_quote"], 0)

    def test_exhausted_retries_halt_then_resume(self):
        tmp = tempfile.mkdtemp()
        wf, _ = make({"prepare_quote": 3}, tmp)
        wf.run()
        self.assertEqual(wf.state["status"], "FAILED")
        wf2, _ = make({}, tmp)          # "new process", same state file, service recovered
        wf2.run()
        self.assertEqual(wf2.state["status"], "PAUSED")
        self.assertEqual(wf2.state["next_step"], 2)

    def test_state_survives_restart_while_paused(self):
        tmp = tempfile.mkdtemp()
        wf, _ = make(tmp=tmp); wf.run()
        wf2, t2 = make(tmp=tmp); wf2.approve(); wf2.run()
        self.assertEqual(wf2.state["status"], "COMPLETE")
        self.assertEqual(t2.calls["check_availability"], 0)  # earlier steps not re-run


if __name__ == "__main__":
    unittest.main()
