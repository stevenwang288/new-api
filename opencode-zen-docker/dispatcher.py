#!/usr/bin/env python3
import itertools, json, os, re, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "4010"))
KEY = os.environ.get("API_KEY", "opencode-zen-key")
LANES = os.environ["LANES"].split(",")
cursor = itertools.cycle(LANES)
STATE_FILE = os.environ.get("STATE_FILE", "/logs/lane-state.json")
SHORT_COOLDOWN = int(os.environ.get("SHORT_COOLDOWN", "60"))
DEFAULT_QUOTA_COOLDOWN = int(os.environ.get("DEFAULT_QUOTA_COOLDOWN", "300"))
MODEL_COOLDOWN_HEADROOM = int(os.environ.get("MODEL_COOLDOWN_HEADROOM", "5"))

def now():
    return time.time()

def load_state():
    try:
        data = json.loads(Path(STATE_FILE).read_text())
        if isinstance(data, dict) and "lanes" in data and "models" in data:
            return {l: float(data["lanes"].get(l, 0)) for l in LANES}, {l: {m: float(t) for m, t in data["models"].get(l, {}).items()} for l in LANES}
        legacy = {lane: float(data.get(lane, 0)) for lane in LANES}
        return legacy, {lane: {} for lane in LANES}
    except Exception:
        return {lane: 0.0 for lane in LANES}, {lane: {} for lane in LANES}

paused_until, model_paused = load_state()
last_error = {lane: None for lane in LANES}
lane_state = {lane: "READY" for lane in LANES}
pause_reason = {lane: None for lane in LANES}
recovery_source = {lane: None for lane in LANES}
stats = {lane: {"requests": 0, "success": 0, "errors": 0, "status": {}} for lane in LANES}
prev_state = {lane: "READY" for lane in LANES}
history = []

def save_state():
    path = Path(STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"lanes": paused_until, "models": model_paused}, ensure_ascii=False, sort_keys=True))
    tmp.replace(path)

def healthy(url):
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as response: return response.status == 200
    except Exception: return False

def lane_available(lane, model=None):
    if paused_until.get(lane, 0) > now(): return False
    if model and model_paused.get(lane, {}).get(model, 0) > now(): return False
    return True

def model_state(lane, model):
    t = model_paused.get(lane, {}).get(model, 0)
    return "READY" if t <= now() else "COOLDOWN"

def cooldown(body, headers, status, retry_after_from_header=None):
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    retry_after = headers.get("Retry-After", ""); import sys; print(f"CD_INPUT status={status} retry_after={repr(retry_after)}",file=sys.stderr,flush=True)
    try:
        for _ in range(3):
            parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, (dict, list)) else str(parsed)
            if isinstance(parsed, dict):
                text += " " + " ".join(str(v) for v in parsed.values())
    except Exception:
        pass
    seconds = 0
    if retry_after.isdigit():
        seconds = max(seconds, int(retry_after))
    elif retry_after:
        try:
            seconds = max(seconds, int(max(0, datetime.strptime(retry_after, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc).timestamp() - now())))
        except ValueError:
            pass
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:hours?|小时|时)", text, re.I):
        seconds = max(seconds, float(m.group(1)) * 3600)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:minutes?|分钟|分)", text, re.I):
        seconds = max(seconds, float(m.group(1)) * 60)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:seconds?|秒)", text, re.I):
        seconds = max(seconds, float(m.group(1)))
    for m in re.finditer(r"retry(?:[-_ ]?(?:after|delay))?[^0-9]{0,40}(\d+(?:\.\d+)?)\s*s(?:econds?)?", text, re.I):
        seconds = max(seconds, float(m.group(1)))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*s\b", text, re.I):
        seconds = max(seconds, float(m.group(1)))
    for value in re.findall(r"(?:retry[-_ ]?after|reset|resume|recover|恢复|重置)[^0-9]{0,40}(\d{10,13})", text, re.I):
        stamp = int(value) / (1000 if len(value) > 10 else 1)
        if stamp > now(): seconds = max(seconds, int(stamp - now()))
    for value in re.findall(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}", text):
        try:
            stamp = datetime.fromisoformat(value.replace("/", "-")).replace(tzinfo=timezone.utc).timestamp()
            if stamp > now(): seconds = max(seconds, int(stamp - now()))
        except ValueError:
            pass
    quota = bool(re.search(r"quota|credit|balance|billing|payment|account.*(limit|deplet|exhaust)|额度|余额|耗尽|用完|账户.*(限制|耗尽)|exhausted|insufficient|no provider available", text, re.I))
    if seconds > 0:
        return max(int(seconds) + 1, SHORT_COOLDOWN), "quota" if quota else "rate_limit"
    if quota: return DEFAULT_QUOTA_COOLDOWN, "quota"
    return SHORT_COOLDOWN, "rate_limit"

def extract_model(body):
    if not body: return None
    try:
        parsed = json.loads(body.decode("utf-8", "replace"))
        return parsed.get("model") if isinstance(parsed, dict) else None
    except Exception:
        return None

def fetch_models():
    merged = []
    seen = set()
    for lane in LANES:
        if not healthy(lane): continue
        try:
            req = urllib.request.Request(lane + "/v1/models", headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
            for item in data.get("data", []):
                mid = item.get("id")
                if mid and mid not in seen:
                    seen.add(mid)
                    merged.append(item)
        except Exception:
            continue
    merged.sort(key=lambda x: x.get("id", ""))
    return merged

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def forward(self, lane, body=b""):
        started = time.time()
        stats[lane]["requests"] += 1
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "authorization")}; headers["Authorization"] = f"Bearer {KEY}"; headers["Content-Length"] = str(len(body)) if body else "0"
        request = urllib.request.Request(lane + self.path, data=body if body else None, method=self.command, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(); code = response.status; response_headers = response.headers
            stats[lane]["success"] += 1; stats[lane]["status"][str(code)] = stats[lane]["status"].get(str(code), 0) + 1; last_error[lane] = None
            history.append({"time": time.time(), "lane": lane, "status": code, "kind": "success", "duration_ms": round((time.time() - started) * 1000)})
            del history[:-100]
            self.send_response(code); self.send_header("Content-Type", response_headers.get("Content-Type", "application/json")); self.send_header("Content-Length", str(len(data))); self.send_header("X-Dispatch-Lane", lane); self.end_headers(); self.wfile.write(data)
            return True
        except urllib.error.HTTPError as error:
            data = error.read()
            if error.code in (400, 404, 405, 415):
                stats[lane]["errors"] += 1; stats[lane]["status"][str(error.code)] = stats[lane]["status"].get(str(error.code), 0) + 1; last_error[lane] = {"status": error.code, "kind": "endpoint_not_supported", "at": time.time(), "message": data.decode("utf-8", "replace")[:500]}
                history.append({"time": time.time(), "lane": lane, "status": error.code, "kind": "endpoint_not_supported", "duration_ms": round((time.time() - started) * 1000)}); del history[:-100]
                print(json.dumps({"lane": lane, "status": error.code, "kind": "endpoint_not_supported", "cooldown_seconds": 0, "body": data.decode("utf-8", "replace")}, ensure_ascii=False), flush=True)
                self.send_response(error.code); self.send_header("Content-Type", error.headers.get("Content-Type", "application/json")); self.send_header("Content-Length", str(len(data))); self.send_header("X-Dispatch-Lane", lane); self.end_headers(); self.wfile.write(data)
                return True
            delay, kind = cooldown(data, error.headers, error.code, error.headers.get("Retry-After")); import sys; print(f"CD_RESULT lane={lane} delay={delay} kind={kind}",file=sys.stderr,flush=True)
            model = extract_model(body)
            if model:
                model_paused.setdefault(lane, {})[model] = time.time() + delay
            else:
                paused_until[lane] = time.time() + delay
            lane_state[lane] = "QUOTA_EXHAUSTED" if kind == "quota" else "COOLDOWN"
            pause_reason[lane] = kind
            recovery_source[lane] = "upstream" if delay != DEFAULT_QUOTA_COOLDOWN and delay != SHORT_COOLDOWN else "estimated"
            stats[lane]["errors"] += 1; stats[lane]["status"][str(error.code)] = stats[lane]["status"].get(str(error.code), 0) + 1; last_error[lane] = {"status": error.code, "kind": kind, "at": time.time(), "message": data.decode("utf-8", "replace")[:500]}
            history.append({"time": time.time(), "lane": lane, "status": error.code, "kind": kind, "duration_ms": round((time.time() - started) * 1000)}); del history[:-100]
            save_state()
            print(json.dumps({"lane": lane, "status": error.code, "kind": kind, "cooldown_seconds": delay, "model": model, "body": data.decode("utf-8", "replace")}, ensure_ascii=False), flush=True)
            return False
        except Exception as error:
            paused_until[lane] = time.time() + SHORT_COOLDOWN
            lane_state[lane] = "NETWORK_ERROR"
            pause_reason[lane] = "network"
            recovery_source[lane] = "estimated"
            stats[lane]["errors"] += 1; stats[lane]["status"]["502"] = stats[lane]["status"].get("502", 0) + 1; last_error[lane] = {"status": 502, "kind": "network", "at": time.time(), "message": str(error)[:500]}
            history.append({"time": time.time(), "lane": lane, "status": 502, "kind": "network", "duration_ms": round((time.time() - started) * 1000)}); del history[:-100]
            save_state()
            print(json.dumps({"lane": lane, "status": 502, "kind": "network", "cooldown_seconds": SHORT_COOLDOWN, "error": str(error)}), flush=True)
            return False
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/status", "/v1/status"):
            n = now()
            out = []
            for lane in LANES:
                lane_pause = paused_until[lane]
                model_times = [t for t in model_paused.get(lane, {}).values() if t > n]
                _cur_state = "READY" if (lane_pause <= n and not model_times) else "COOLDOWN"
                if prev_state.get(lane) != "READY" and _cur_state == "READY":
                    stats[lane] = {"requests": 0, "success": 0, "errors": 0, "status": {}}
                    last_error[lane] = None
                prev_state[lane] = _cur_state
                recovery = lane_pause if lane_pause > n else (max(model_times) if model_times else 0)
                state = lane_state[lane] if lane_pause > n else ("COOLDOWN" if model_times else "READY")
                out.append({"lane": lane, "state": state, "pause_reason": pause_reason[lane], "recovery_at": recovery if recovery > 0 else None, "recovery_source": recovery_source[lane], "remaining_seconds": max(0, round(max(lane_pause, recovery) - n)), "paused": max(0, round(lane_pause - n)), "cooldown_until": lane_pause, "last_error": last_error[lane], "model_cooldowns": {m: round(t - n) for m, t in model_paused.get(lane, {}).items() if t > n}, **stats[lane]})
            lanes = out
            data = json.dumps({"status": "ok", "time": n, "lanes": lanes, "recent": history[-100:]}, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path == "/dashboard":
            html = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Dispatcher 状态</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font:14px -apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;background:#0d1117;color:#e6edf3;padding:24px}
h1{font-size:20px;font-weight:600;margin-bottom:4px;color:#e6edf3}
#summary{font-size:13px;color:#8b949e;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #21262d}
.lane-name{font-size:13px;font-weight:600;color:#e6edf3;font-family:ui-monospace,SFMono-Regular,SF Mono,Consolas,Liberation Mono,monospace}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:500}
.badge-cooldown{background:#7f1d1d;color:#f5a5a5}
.badge-ready{background:#1b4332;color:#52b788}
.row{display:flex;justify-content:space-between;font-size:12px;padding:4px 0;color:#8b949e}
.row .value{color:#e6edf3}
.row .label{color:#8b949e}
.countdown{font-size:22px;font-weight:700;text-align:center;padding:10px 0 4px;color:#e6edf3;font-variant-numeric:tabular-nums}
.countdown small{font-size:12px;font-weight:400;color:#8b949e;display:block;margin-top:2px}
.recovery{font-size:11px;color:#8b949e;text-align:center;padding:2px 0 6px}
.stats{display:flex;gap:0;margin-top:8px;padding-top:8px;border-top:1px solid #21262d;font-size:11px;color:#8b949e}
.stats span{flex:1;text-align:center}
.stats span+span{border-left:1px solid #21262d}
</style></head><body><h1>Dispatcher 状态</h1><p id=summary></p><div class=grid id=rows></div><script>
function fmt(s){let h=Math.floor(s/3600),m=Math.floor((s%3600)/60),r=s%60;return h+"h "+m+"m "+r+"s"}
function fmtTime(t){let d=new Date(t*1000);return d.getFullYear()+"/"+(d.getMonth()+1)+"/"+d.getDate()+" "+d.toLocaleTimeString("zh-CN",{hour12:false})}
async function refresh(){let d=await fetch("/status").then(r=>r.json()),ok=0;rows.innerHTML=d.lanes.map(x=>{let live=x.paused===0&&Object.keys(x.model_cooldowns||{}).length===0;if(live)ok++;let r=x.remaining_seconds;let t=x.recovery_at;return '<div class=card><div class=card-header><span class=lane-name>'+x.lane.replace(/^http:\/\//,"")+'</span><span class="badge '+(live?"badge-ready":"badge-cooldown")+'">'+(live?"READY":"COOLDOWN")+'</span></div><div class=countdown>'+(live?"READY":fmt(r))+'<small>'+(live?"":"预计恢复倒计时")+'</small></div>'+(t?'<div class=recovery>预计恢复时间: '+fmtTime(t)+'</div>':'')+'<div class=stats><span>请求数: '+x.requests+'</span><span>成功: '+x.success+'</span><span>错误数: '+x.errors+'</span></div></div>'}).join("");summary.textContent=ok+"/"+d.lanes.length+" 条线路就绪 | "+d.lanes.filter(x=>x.paused===0).length+" online | "+new Date().toLocaleTimeString()}
setInterval(refresh,2000);refresh()
</script>"""
            data=html.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        if path in ("/health", "/v1/health"):
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", "15"); self.end_headers(); self.wfile.write(b'{"status":"ok"}'); return
        if path in ("/v1/models", "/models"):
            models = fetch_models()
            if models:
                data = json.dumps({"object": "list", "data": models}, ensure_ascii=False).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            data = json.dumps({"error": {"type": "temporarily_unavailable", "message": "所有 OpenCode 容器当前都在限流、额度暂停或不可用，请稍后重试"}}, ensure_ascii=False).encode()
            self.send_response(503); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if self.command == "POST" else b""
        model = extract_model(body)
        for _ in LANES:
            lane = next(cursor)
            if not lane_available(lane, model): continue
            if self.forward(lane, body): return
        data = json.dumps({"error": {"type": "temporarily_unavailable", "message": "所有 OpenCode 容器当前都在限流、额度暂停或不可用，请稍后重试"}}, ensure_ascii=False).encode()
        self.send_response(503); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_POST = do_GET

ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
