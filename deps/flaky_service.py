"""flaky_service.py — service HTTP volontairement instable (stdlib uniquement).
Lancer : python flaky_service.py [port] (port par défaut : 8080)
Piloter : http://localhost:8080/admin?fail_rate=0.3&latency=0.2&latency_reco=3&down=0&fail_after=0
"""
import json, random, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CONFIG = {"fail_rate": 0.0,  # probabilité d'erreur 503 avant traitement
          "fail_after": 0.0,  # probabilité de 503 APRÈS traitement (réponse perdue)
          "latency": 0.05,  # latence moyenne (s) des endpoints
          "latency_reco": 0.05,  # latence moyenne (s) de /reco
          "down": 0}  # 1 = service totalement indisponible

CHARGES, PAYMENTS = [], {}  # paiements débités, clés d'idempotence vues
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _instable(self, latence):
        if CONFIG["down"]:
            self._send(503, {"error": "service down"})
            return True
        time.sleep(latence * random.uniform(0.5, 1.5))
        if random.random() < CONFIG["fail_rate"]:
            self._send(503, {"error": "erreur transitoire"})
            return True
        return False

    def do_GET(self):
        url, q = urlparse(self.path), parse_qs(urlparse(self.path).query)

        if url.path == "/admin":
            for k in CONFIG:
                if k in q:
                    CONFIG[k] = float(q[k][0])
            # Ajout projet final : remise à zéro des compteurs entre deux expériences.
            if q.get("reset", ["0"])[0] == "1":
                with LOCK:
                    CHARGES.clear()
                    PAYMENTS.clear()
            return self._send(200, {**CONFIG, "charges": len(CHARGES), "cles": len(PAYMENTS)})

        if url.path == "/health":
            return self._send(200, {"status": "up"})

        if url.path.startswith("/reco/"):
            if not self._instable(CONFIG["latency_reco"]):
                self._send(200, {"items": ["A12", "B07", "C33"]})
            return

        if url.path.startswith("/stock/"):
            if not self._instable(CONFIG["latency"]):
                self._send(200, {
                    "sku": url.path.split("/")[-1],
                    "stock": random.randint(0, 50)
                })
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/payments":
            return self._send(404, {"error": "not found"})

        corps = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
        )

        if self._instable(CONFIG["latency"]):
            return

        cle = self.headers.get("Idempotency-Key")

        with LOCK:
            if cle and cle in PAYMENTS:
                return self._send(200, PAYMENTS[cle])  # rejeu : pas de nouveau débit

            paiement = {"id": len(CHARGES) + 1, "montant": corps.get("montant")}
            CHARGES.append(paiement)

            if cle:
                PAYMENTS[cle] = paiement

            if random.random() < CONFIG["fail_after"]:
                return self._send(503, {"error": "réponse perdue"})  # débité mais le client ne le sait pas

            self._send(201, paiement)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"flaky_service sur http://localhost:{port}")
    ThreadingHTTPServer.request_queue_size = 128  # file d'attente TCP plus large
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("", port), Handler).serve_forever()
