#!/usr/bin/env python3
import json, os, ssl, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM", "https://opencode.ai/zen/v1")
PORT = int(os.environ["PORT"])
LANE = os.environ["LANE"]
API_KEY = os.environ["API_KEY"]
PROXY = os.environ["HTTPS_PROXY"]
MODELS = ["big-pickle", "deepseek-v4-flash-free", "mimo-v2.5-free", "ling-3.0-flash-free", "nemotron-3-ultra-free", "north-mini-code-free", "laguna-s-2.1-free"]
# Content routing: requests that carry image media get routed to the multimodal model.
TEXT_MODEL = os.environ.get("TEXT_MODEL", "deepseek-v4-flash-free")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "mimo-v2.5-free")
ALIASES = {m: m for m in MODELS}
ALIASES.update({f"opencode/{m}": m for m in MODELS})
ALIASES.update({f"HK-OC/{m}": m for m in MODELS})
ALIASES.update({f"936-OC/{m}": m for m in MODELS})
ALIASES.update({f"961-zen/{m}": m for m in MODELS})

CHAT_ENDPOINTS = ("/chat/completions", "/v1/chat/completions")
RESP_ENDPOINTS = ("/responses", "/v1/responses")


def _has_image(value):
    if isinstance(value, dict):
        vtype = value.get("type")
        if vtype in ("image", "image_url", "input_image"):
            return True
        if "image_url" in value or "image_data" in value or "input_image" in value:
            return True
        return any(_has_image(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_image(v) for v in value)
    return False


def contains_image(request):
    if not isinstance(request, dict):
        return False
    if isinstance(request.get("messages"), list):
        for msg in request["messages"]:
            content = msg.get("content")
            if isinstance(content, str) and _has_image(content):
                return True
            if isinstance(content, list) and _has_image(content):
                return True
    if isinstance(request.get("input"), list) and _has_image(request["input"]):
        return True
    return False


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", )
GEMINI_UPSTREAM = os.environ.get("GEMINI_UPSTREAM", "https://generativelanguage.googleapis.com/v1beta/openai")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "AIzaSyCJML9pccPW3EoXtEtRMX6s34rFSSGXcvM")

def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))

def opener_direct():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"lane={LANE} {fmt % args}", flush=True)

    def auth(self):
        return self.headers.get("Authorization", "").removeprefix("Bearer ").strip() == API_KEY

    def send_json(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Lane", LANE)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/v1/health"):
            self.send_json(200, {"status": "ok", "lane": LANE})
            return
        if path in ("/models", "/v1/models"):
            if not self.auth():
                self.send_json(401, {"error": "unauthorized"})
                return
            self.send_json(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": f"lane-{LANE}"} for m in MODELS]})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.auth():
            self.send_json(401, {"error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        if path in CHAT_ENDPOINTS:
            upstream_path = "/chat/completions"
        elif path in RESP_ENDPOINTS:
            upstream_path = "/responses"
        else:
            self.send_json(404, {"error": "not found"})
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            request = json.loads(raw or b"{}")
        except ValueError:
            self.send_json(400, {"error": "invalid json"})
            return
        original = request.get("model", "")
        base_model = ALIASES.get(original, original)
        request["model"] = IMAGE_MODEL if contains_image(request) else base_model
        print(f"lane={LANE} route model={original} -> {request['model']} image={contains_image(request)}", flush=True)
        is_stream = bool(request.get("stream", False))
        use_gemini = base_model == GEMINI_MODEL
        if use_gemini:
            _up = GEMINI_UPSTREAM + upstream_path
            _hd = {"Content-Type": "application/json", "User-Agent": "opencode/zen", "Authorization": "Bearer " + GEMINI_KEY}
            _opn = opener_direct
        else:
            _up = UPSTREAM + upstream_path
            _hd = {"Content-Type": "application/json", "User-Agent": "opencode/zen"}
            _opn = opener
        upstream = urllib.request.Request(
            _up,
            data=json.dumps(request).encode(),
            method="POST",
            headers=_hd,
        )
        try:
            with _opn().open(upstream, timeout=300) as response:
                data = response.read()
                code = response.status
                ctype = response.headers.get("Content-Type", "application/json")
            if not is_stream and ctype.startswith("application/json"):
                try:
                    result = json.loads(data)
                    result["model"] = original or result.get("model")
                    data = json.dumps(result)
                except (ValueError, TypeError):
                    pass
            body = data if isinstance(data, bytes) else data.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype if is_stream else "application/json")
            self.send_header("X-Lane", LANE)
            if is_stream:
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
            else:
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            ra = error.headers.get("Retry-After")
            self.send_response(error.code)
            if ra:
                self.send_header("Retry-After", ra)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(json.dumps({"error": body}).encode())))
            self.send_header("X-Lane", LANE)
            self.end_headers()
            self.wfile.write(json.dumps({"error": body}).encode())
        except Exception as error:
            self.send_json(502, {"error": "upstream failed", "details": str(error), "lane": LANE})


ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
