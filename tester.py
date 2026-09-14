# -*- coding: utf-8 -*-
# HiVo Proxies — Core Engine
import base64, hashlib, json, logging, os, random, re, socket, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape
from urllib.parse import urlparse, parse_qs

import requests
from store import STORE

TCP_TIMEOUT = float(os.environ.get("TCP_TIMEOUT", "3"))
MAX_TO_TEST = int(os.environ.get("MAX_TO_TEST", "5000"))
WORKERS = int(os.environ.get("TCP_WORKERS", "200"))
REFRESH_EVERY = int(os.environ.get("REFRESH_EVERY", "900"))
SUB_LIMIT = int(os.environ.get("SUB_LIMIT", "500"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo.core")
logging.getLogger("urllib3").setLevel(logging.WARNING)

S = {"good": [], "tested": 0, "fetched": 0, "last": None, "sub": None}
LOCK = threading.Lock()
FORCE = threading.Event()

URI_RE = re.compile(r"(?:https?://t\.me/proxy|tg://proxy)\?[^\s\"'<>]+", re.IGNORECASE)

DEFAULT_SOURCES = [
    "https://mtpro.xyz/api/?type=mtproto",
    "https://t.me/s/MTProtoNew",
    "https://t.me/s/mtprotoproxy",
    "https://t.me/s/ProxyMTProto",
    "https://t.me/s/MTPROTOPROXY_IR",
    "https://t.me/s/proxy_mtproto",
    "https://t.me/s/mtprotoproxy_fast",
]

_GEO = {}
_GEO_LOCK = threading.Lock()
_SRC_HEALTH = {}
_H_LOCK = threading.Lock()


def parse_proxy(uri):
    try:
        s = uri.strip()
        if s.startswith("tg://"):
            s = "https://t.me/" + s[5:]
        p = urlparse(s)
        q = parse_qs(p.query)
        host = q.get("server", [""])[0].strip()
        try:
            port = int(q.get("port", ["0"])[0])
        except Exception:
            return None
        secret = q.get("secret", [""])[0].strip()
        if not host or not (0 < port < 65536) or not secret:
            return None
        key = host.lower() + ":" + str(port) + ":" + secret.lower()
        fp = hashlib.sha1(key.encode()).hexdigest()[:12]
        return {"host": host, "port": port, "secret": secret, "fp": fp, "uri": uri}
    except Exception:
        return None


def parse_json_source(text):
    out = []
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("proxies", [])
        for item in items:
            if not isinstance(item, dict):
                continue
            host = str(item.get("host") or item.get("server") or item.get("ip") or "").strip()
            try:
                port = int(item.get("port", 0))
            except Exception:
                continue
            secret = str(item.get("secret") or "").strip()
            if host and 0 < port < 65536 and secret:
                out.append("https://t.me/proxy?server=" + host + "&port=" + str(port) + "&secret=" + secret)
    except Exception:
        pass
    return out


def fetch_source(url):
    r = requests.get(url, timeout=25, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HiVo-Proxies/1.0)"})
    r.raise_for_status()
    text = r.text
    stripped = text.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        res = parse_json_source(stripped)
        if res:
            return res
    text = unescape(text)
    return URI_RE.findall(text)


def _safe_fetch(url):
    with _H_LOCK:
        h = _SRC_HEALTH.setdefault(url, {"ok": 0, "fail": 0, "count": 0, "cooldown": 0})
        if h["cooldown"] > time.time():
            return None
    try:
        res = fetch_source(url)
        with _H_LOCK:
            h["ok"] += 1
            h["fail"] = 0
            h["count"] = len(res)
        return res
    except Exception as e:
        with _H_LOCK:
            h["fail"] += 1
            if h["fail"] >= 3:
                h["cooldown"] = time.time() + 1800
        log.warning("src fail: " + str(e))
        return None


def current_sources():
    srcs = STORE.data.get("sources")
    if isinstance(srcs, list) and srcs:
        return list(srcs)
    return list(DEFAULT_SOURCES)


def fetch_all():
    out = []
    with ThreadPoolExecutor(8) as pool:
        for res in pool.map(_safe_fetch, current_sources()):
            if res:
                out += res
    return out


def source_report():
    out = []
    with _H_LOCK:
        snap = {u: dict(h) for u, h in _SRC_HEALTH.items()}
    for u in current_sources():
        h = snap.get(u, {})
        out.append({
            "url": u,
            "ok": h.get("ok", 0),
            "fail": h.get("fail", 0),
            "count": h.get("count", 0),
            "cooldown": max(0, int(h.get("cooldown", 0) - time.time())),
        })
    return out


def tcp_ping(host, port):
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None


def probe(p):
    ms = tcp_ping(p["host"], p["port"])
    if ms is None:
        return None
    p["latency"] = ms
    return p


def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    return "".join(chr(ord(c) + 127397) for c in cc.upper())


def geo_batch(items):
    todo = sorted({p["host"] for p in items if p.get("host") and p["host"] not in _GEO})[:100]
    if not todo:
        return
    try:
        r = requests.post(
            "http://ip-api.com/batch?fields=status,country,countryCode,city,query",
            json=todo, timeout=12)
        for d in r.json():
            if d.get("status") == "success":
                with _GEO_LOCK:
                    _GEO[d["query"]] = (flag_of(d.get("countryCode")),
                                        d.get("country", ""),
                                        d.get("city", ""))
    except Exception:
        pass
    for p in items:
        with _GEO_LOCK:
            f, n, c = _GEO.get(p["host"], ("🌐", "", ""))
        p["flag"] = f
        p["country"] = n
        p["city"] = c


def score_of(p):
    ms = p.get("latency", 9999)
    if ms < 100:
        return 100
    if ms < 300:
        return 95
    if ms < 600:
        return 85
    if ms < 1000:
        return 70
    if ms < 2000:
        return 50
    return 30


def dedup(items):
    best = {}
    for p in items:
        fp = p.get("fp")
        if not fp:
            continue
        cur = best.get(fp)
        if cur is None or p.get("latency", 9999) < cur.get("latency", 9999):
            best[fp] = p
    return list(best.values())


def publish(items):
    alive = [p for p in dedup(items) if p.get("latency") is not None]
    if not alive:
        return
    for p in alive:
        p["score"] = score_of(p)
    alive.sort(key=lambda p: p["latency"])
    with LOCK:
        S["good"] = alive
        S["last"] = datetime.now()


def export_uri(p):
    return ("https://t.me/proxy?server=" + p["host"]
            + "&port=" + str(p["port"])
            + "&secret=" + p["secret"])


def upload_sub(text):
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    api = "https://api.github.com/repos/" + repo + "/contents/proxies.txt"
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(api, headers=headers, timeout=30)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": "update proxies",
                "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        r2 = requests.put(api, headers=headers, json=body, timeout=30)
        if r2.status_code in (200, 201):
            return "https://raw.githubusercontent.com/" + repo + "/main/proxies.txt"
    except Exception as e:
        log.warning("sub up: " + str(e))
    return None


def cycle(n_max, label):
    uris = fetch_all()
    uniq = list(dict.fromkeys(uris))
    random.shuffle(uniq)
    with LOCK:
        S["fetched"] = len(uniq)
        S["tested"] = 0

    seen, parsed = set(), []
    for u in uniq:
        if len(parsed) >= n_max:
            break
        p = parse_proxy(u)
        if not p or p["fp"] in seen:
            continue
        seen.add(p["fp"])
        parsed.append(p)

    total = len(parsed)
    log.info("[" + label + "] candidates: " + str(total))

    alive = []
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = [pool.submit(probe, p) for p in parsed]
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                alive.append(r)
            done += 1
            if done % 100 == 0:
                with LOCK:
                    S["tested"] = done
                publish(alive)
        with LOCK:
            S["tested"] = done

    geo_batch(alive)
    publish(alive)
    log.info("[" + label + "] alive: " + str(len(S["good"])))

    try:
        with LOCK:
            good = list(S["good"][:SUB_LIMIT])
        if good:
            text = "\n".join(export_uri(p) for p in good) + "\n"
            url = upload_sub(text)
            with LOCK:
                S["sub"] = url
    except Exception:
        log.exception("sub")


def refresh_loop():
    log.info("engine started")
    while True:
        try:
            cycle(MAX_TO_TEST, "full")
        except Exception:
            log.exception("cycle")
        FORCE.wait(REFRESH_EVERY)
        FORCE.clear()


def test_single(uri):
    p = parse_proxy(uri)
    if not p:
        return None
    ms = tcp_ping(p["host"], p["port"])
    if ms is None:
        return None
    p["latency"] = ms
    p["score"] = score_of(p)
    geo_batch([p])
    return p
