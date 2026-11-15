"""Loopback-only, dependency-free server for the local benchmark UI."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import traceback
from urllib.parse import urlsplit
import uuid

from . import __version__
from .batch import provenance, run_series
from .domain import Config
from .simulation import Comparison


WEB = Path(__file__).resolve().parents[1] / "web"


class Conflict(ValueError):
    pass


class Application:
    def __init__(self):
        self.lock = threading.RLock()
        self.comparison = Comparison()
        self.session = uuid.uuid4().hex
        self.jobs = {}
        self.job_lock = threading.Lock()

    def snapshot(self, world=False):
        return {"session": self.session, **self.comparison.snapshot(include_world=world)}

    def reset(self, data):
        config = Config.parse(data.get("config", {}))
        comparison = Comparison(config, data.get("mode", "rescue"))
        with self.lock:
            self.comparison = comparison
            self.session = uuid.uuid4().hex
            return self.snapshot(True)

    def step(self, data):
        steps = data.get("steps", 1)
        if type(steps) is not int or not 1 <= steps <= 60:
            raise ValueError("steps: целое число от 1 до 60.")
        with self.lock:
            if data.get("session") != self.session:
                raise Conflict("Сценарий уже изменился. Обновите страницу.")
            self.comparison.step(steps, snapshot=False)
            return self.snapshot()

    def start_batch(self, data):
        config = Config.parse(data.get("config", {}))
        mode, count = data.get("mode", "rescue"), data.get("count", 5)
        if mode not in {"scout", "rescue"}:
            raise ValueError("Неизвестный режим.")
        if type(count) is not int or not 1 <= count <= 20:
            raise ValueError("Число карт: целое от 1 до 20.")
        if config.seed+count-1 > 2147483647:
            raise ValueError("Слишком большой начальный seed.")
        with self.job_lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise Conflict("Серия уже выполняется. Дождитесь её или отмените.")
            while len(self.jobs) >= 4:
                del self.jobs[next(iter(self.jobs))]
            ident = uuid.uuid4().hex
            event = threading.Event()
            self.jobs[ident] = {"id": ident, "status": "running", "completed": 0,
                                "requested": count, "cancel": event, "result": None, "error": None}
        def progress(done, total):
            with self.job_lock:
                self.jobs[ident]["completed"] = done
        def worker():
            try:
                result = run_series(config, mode, count, event, progress)
                with self.job_lock:
                    job = self.jobs[ident]
                    job["result"] = result
                    job["status"] = "cancelled" if result["cancelled"] else "done"
            except Exception:
                traceback.print_exc()
                with self.job_lock:
                    self.jobs[ident]["status"] = "error"
                    self.jobs[ident]["error"] = "Ошибка серии. Подробности в окне сервера."
        threading.Thread(target=worker, name="rescue-batch", daemon=True).start()
        return {"id": ident, "status": "running", "completed": 0, "requested": count}

    def batch(self, ident):
        with self.job_lock:
            if ident not in self.jobs:
                raise ValueError("Серия не найдена.")
            return {k: v for k, v in self.jobs[ident].items() if k != "cancel"}

    def cancel_batch(self, ident):
        with self.job_lock:
            if ident not in self.jobs:
                raise ValueError("Серия не найдена.")
            self.jobs[ident]["cancel"].set()
        return {"ok": True}

    def close(self):
        with self.job_lock:
            for job in self.jobs.values():
                job["cancel"].set()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app=None):
        self.app = app or Application()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "RescueBench/" + __version__

    def log_message(self, format, *args):
        # Keep the console useful for errors; animation polling is intentionally quiet.
        if args and str(args[1]) not in {"200", "304"}:
            super().log_message(format, *args)

    def allowed_host(self):
        try:
            host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            return host in {"127.0.0.1", "localhost", "::1"}
        except ValueError:
            return False

    def send(self, status, body, mime="application/json; charset=utf-8"):
        if mime.startswith("application/json"):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, {"error": "Только локальный доступ."})
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                return self.send(200, {"ok": True, "version": __version__})
            if path in {"/api/state", "/api/export"}:
                with self.server.app.lock:
                    data = self.server.app.snapshot(True)
                    if path.endswith("export"):
                        data["metadata"] = provenance()
                    return self.send(200, data)
            if path.startswith("/api/batch/"):
                return self.send(200, self.server.app.batch(path.rsplit("/",1)[-1]))
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/index.html": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                      "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if path in static:
                name, mime = static[path]
                return self.send(200, (WEB/name).read_bytes(), mime)
            return self.send(404, {"error": "Не найдено."})
        except ValueError as error:
            return self.send(400, {"error": str(error)})
        except Exception:
            traceback.print_exc()
            return self.send(500, {"error": "Ошибка сервера. Подробности в консоли."})

    def do_POST(self):
        if not self.allowed_host():
            return self.send(403, {"error": "Только локальный доступ."})
        origin = self.headers.get("Origin")
        expected = "http://" + self.headers.get("Host", "")
        if ((origin and origin != expected) or self.headers.get("X-Rescue-Benchmark") != "1"):
            return self.send(403, {"error": "Разрешены запросы только из локального интерфейса."})
        if self.headers.get_content_type() != "application/json":
            return self.send(415, {"error": "Нужен Content-Type: application/json."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 16384:
                return self.send(413, {"error": "Допустим JSON размером до 16 КБ."})
            data = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(
                ValueError("Неконечные числа запрещены.")))
            if not isinstance(data, dict):
                raise ValueError("Нужен JSON-объект.")
            path = urlsplit(self.path).path
            app = self.server.app
            if path == "/api/reset":
                result = app.reset(data)
            elif path == "/api/step":
                result = app.step(data)
            elif path == "/api/batch":
                result = app.start_batch(data)
            elif path == "/api/batch/cancel":
                result = app.cancel_batch(data.get("id"))
            else:
                return self.send(404, {"error": "Не найдено."})
            return self.send(200, result)
        except Conflict as error:
            return self.send(409, {"error": str(error)})
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            return self.send(400, {"error": str(error)})
        except Exception:
            traceback.print_exc()
            return self.send(500, {"error": "Ошибка сервера. Подробности в консоли."})
