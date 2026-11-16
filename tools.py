"""Mocked external services. Nothing here touches the network."""
from collections import Counter
from engine import TransientError, PermanentError

DEFAULT_REQUEST = {
    "customer": "Jane Doe", "origin": "KSJC", "destination": "KLAS",
    "date": "2026-12-04", "passengers": 6,
}

FLEET = [  # hardcoded "availability system"
    {"tail": "N450AV", "type": "Gulfstream G450", "seats": 14, "mph": 480, "rate": 9800, "available": True},
    {"tail": "N300PH", "type": "Phenom 300",      "seats": 6,  "mph": 450, "rate": 4200, "available": True},
    {"tail": "N560XL", "type": "Citation XLS",    "seats": 8,  "mph": 430, "rate": 5100, "available": False},
]
DISTANCE_MILES = {("KSJC", "KLAS"): 390}
FET = 0.075  # US federal excise tax on charter


class MockTools:
    def __init__(self, failures=None):
        self.failures = dict(failures or {})   # {tool_name: times to fail before succeeding}
        self.calls = Counter()

    def _maybe_fail(self, name):
        self.calls[name] += 1
        if self.failures.get(name, 0) > 0:
            self.failures[name] -= 1
            raise TransientError("Temporary API timeout")

    def check_availability(self, req):
        self._maybe_fail("check_availability")
        options = [a for a in FLEET if a["available"] and a["seats"] >= req["passengers"]]
        if not options:
            raise PermanentError("No aircraft available for this request")
        return {"options": options}

    def prepare_quote(self, req, availability):
        self._maybe_fail("prepare_quote")
        aircraft = min(availability["options"], key=lambda a: a["rate"])
        miles = DISTANCE_MILES[(req["origin"], req["destination"])]
        hours = round(miles / aircraft["mph"], 1)
        flight = round(hours * aircraft["rate"], 2)
        taxes = round(flight * FET, 2)
        total = round(flight + taxes, 2)
        return {
            "aircraft": f"{aircraft['type']} ({aircraft['tail']})",
            "flight_hours": hours, "flight_cost": flight, "taxes": taxes, "total": total,
            "draft": (f"Hi {req['customer']}, {req['origin']} to {req['destination']} on "
                      f"{req['date']} for {req['passengers']} passengers: {aircraft['type']}, "
                      f"~{hours}h, total ${total:,.2f} incl. 7.5% FET."),
        }

    def send_quote(self, quote, idempotency_key):
        self._maybe_fail("send_quote")
        # Real provider would dedupe on the key, so a retry can't double-send.
        return {"message_id": f"MSG-{idempotency_key}", "sent": "mock", "body": quote["draft"]}
