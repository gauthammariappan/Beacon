"""Unit tests for Beacon v2.1 incident manager and FastAPI server."""

import unittest
from fastapi.testclient import TestClient

from beacon.incidents import IncidentManager, IncidentState
from beacon.server import app, incident_manager, handle_serial_line


class TestIncidentsAndServer(unittest.TestCase):
    def setUp(self):
        incident_manager.reset()
        self.client = TestClient(app)

    def test_incident_state_machine_and_contract(self):
        im = IncidentManager(silence_timeout_s=10.0)

        # 1. First beep: spatial location locked -> LOCATED
        inc = im.feed_beep(
            location_result={"rack": "B", "confidence": 0.89, "runner_up": {"rack": "A", "p": 0.06}},
            timestamp=1000.0,
        )
        self.assertIsNotNone(inc)
        self.assertEqual(inc.state, IncidentState.LOCATED)
        self.assertEqual(inc.rack, "B")
        self.assertAlmostEqual(inc.confidence, 0.89, places=2)

        # 2. Cadence locked -> IDENTIFIED
        inc = im.feed_beep(
            location_result={"rack": "B", "confidence": 0.92},
            alarm_result={"meaning": "UPS On Battery", "device": "UPS", "pattern": "P1"},
            timestamp=1002.0,
        )
        self.assertEqual(inc.state, IncidentState.IDENTIFIED)
        self.assertEqual(inc.alarm["meaning"], "UPS On Battery")

        # Verify exact required contract structure:
        # {"id": "inc_1", "state": "IDENTIFIED", "rack": "B", "confidence": 0.89, "alarm": {"meaning": "UPS On Battery"}}
        contract = inc.to_dict()
        self.assertEqual(contract["id"], "inc_1")
        self.assertEqual(contract["state"], "IDENTIFIED")
        self.assertEqual(contract["rack"], "B")
        self.assertAlmostEqual(contract["confidence"], 0.92, places=2)
        self.assertEqual(contract["alarm"]["meaning"], "UPS On Battery")

        # 3. Manual Acknowledge -> ACKNOWLEDGED
        ack = im.acknowledge("inc_1")
        self.assertIsNotNone(ack)
        self.assertEqual(ack.state, IncidentState.ACKNOWLEDGED)

        # 4. Silence timeout after 10 s -> CLEARED
        cleared = im.check_timeout(current_time=1015.0)
        self.assertIsNotNone(cleared)
        self.assertEqual(cleared.state, IncidentState.CLEARED)
        self.assertIsNone(im.get_active_incident())

    def test_get_layout_route(self):
        resp = self.client.get("/layout")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("racks", data)
        self.assertIn("microphones", data)
        rack_ids = [r["id"] for r in data["racks"]]
        self.assertEqual(rack_ids, ["A", "B", "C", "D", "E"])
        mic_ids = [m["id"] for m in data["microphones"]]
        self.assertEqual(mic_ids, ["L", "M", "R"])

    def test_get_model_metrics_route(self):
        resp = self.client.get("/model/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("loudest_mic", data)
        self.assertIn("weighted_centroid", data)
        self.assertIn("random_forest", data)
        self.assertIn("classes", data)

    def test_acknowledge_route(self):
        # Create an incident in the manager
        inc = incident_manager.feed_beep(
            location_result={"rack": "C", "confidence": 0.95},
            alarm_result={"meaning": "UPS On Battery"},
            timestamp=100.0,
        )
        self.assertIsNotNone(inc)
        inc_id = inc.id

        # POST /incidents/{id}/ack
        resp = self.client.post(f"/incidents/{inc_id}/ack")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], inc_id)
        self.assertEqual(data["state"], "ACKNOWLEDGED")

        # Test non-existent incident
        resp404 = self.client.post("/incidents/non_existent_999/ack")
        self.assertEqual(resp404.status_code, 404)

    def test_websocket_live_stream(self):
        # Create an incident in the manager
        inc = incident_manager.feed_beep(
            location_result={"rack": "B", "confidence": 0.89},
            alarm_result={"meaning": "UPS On Battery"},
            timestamp=500.0,
        )
        self.assertIsNotNone(inc)
        inc_id = inc.id

        with self.client.websocket_connect("/live") as ws:
            # 1. First message should be mic_levels or active incident
            msg1 = ws.receive_json()
            self.assertIn("type", msg1)

            # 2. Trigger instant incident push via POST /incidents/{id}/ack
            resp = self.client.post(f"/incidents/{inc_id}/ack")
            self.assertEqual(resp.status_code, 200)

            # 3. Receive the pushed incident state change instantly
            found_incident = False
            for _ in range(5):
                msg = ws.receive_json()
                if msg.get("type") == "incident" and msg.get("state") == "ACKNOWLEDGED":
                    found_incident = True
                    self.assertEqual(msg["rack"], "B")
                    self.assertEqual(msg["alarm"]["meaning"], "UPS On Battery")
                    break

            self.assertTrue(found_incident, "WebSocket should receive instant incident state change")

    def test_frontend_routes(self):
        # 1. API health check (Accept: application/json)
        resp_json = self.client.get("/", headers={"accept": "application/json"})
        self.assertEqual(resp_json.status_code, 200)
        self.assertEqual(resp_json.json().get("system"), "Beacon v2.1 Backend")

        # 2. Browser request to root (Accept: text/html)
        resp_html = self.client.get("/", headers={"accept": "text/html,application/xhtml+xml"})
        self.assertEqual(resp_html.status_code, 200)
        self.assertIn("Beacon v2.1", resp_html.text)

        # 3. /dashboard
        resp_dash = self.client.get("/dashboard")
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn("NOC DASHBOARD", resp_dash.text)

        # 4. /app.js
        resp_js = self.client.get("/app.js")
        self.assertEqual(resp_js.status_code, 200)
        self.assertIn("Beacon v2.1 · Frontend Application", resp_js.text)

        # 5. Static mount /web/index.html & /web/app.js
        resp_static_html = self.client.get("/web/index.html")
        self.assertEqual(resp_static_html.status_code, 200)
        resp_static_js = self.client.get("/web/app.js")
        self.assertEqual(resp_static_js.status_code, 200)


if __name__ == "__main__":
    unittest.main()
