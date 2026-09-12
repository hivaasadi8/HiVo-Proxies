# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Proxies — موتور تست MTProto دولایه
#  TCP پینگ + دست‌دهی واقعی (req_pq → resPQ)
# ══════════════════════════════════════════
import json, logging, os, re, socket, struct, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from Crypto.Cipher import AES

from store import STORE

TCP_TIMEOUT   = 3
MAX_TO_TEST   = 3000
DEEP_LIMIT    = 400
WORKERS       = 200
DEEP_WORKERS  = 20
DEEP_TIMEOUT  = 6
REFRESH_EVERY = 900

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo.proxies")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None}
LOCK = threading.Lock()
GEO = {}
GEO_LOCK = threading.Lock()

LINK_RE = re.compile(r"(?:https?://)?t\.me/proxy\?server=([^&\s<>\"']+)&port=(\d+)&secret=([0-9a-fA-F]{16,})")
TG_RE = re.compile(r"tg://proxy\?server=([^&\s<>\"']+)&port=(\d+)&secret=([0-9a-fA-F]{16,})")
LINE_RE = re.compile(r"^([a-zA-Z0-9.\-]+):(\d+):([0-9a-fA-F]{32,128})\s*$", re.M)

def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    return "".join(chr(ord(c) + 127397) for c in cc.upper())

def geo_batch(items):
    hosts = list({c["server"] for c in items})
    for i in range(0, len(hosts), 100):
        chunk = hosts[i:i + 100]
        try:
            r = requests.post("http://ip-api.com/batch?fields=status,country,countryCode,query",
                              json=chunk, timeout=15)
            for d in r.json():
                if d.get("status") == "success":
                    with GEO_LOCK:
                        GEO[d["query"]] = (flag_of(d.get("countryCode")), d.get("country", ""))
        except Exception:
            continue
    for c in items:
        with GEO_LOCK:
            f, name = GEO.get(c["server"], ("🌐", ""))
        c["flag"], c["country"] = f, name

# ──────────── جمع‌آوری ────────────
def fetch_channel(name):
    name = str(name).strip().lstrip("@")
    name = name.replace("https://t.me/", "").replace("t.me/", "").split("/")[0]
    url = f"https://t.me/s/{name}"
    text = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    text = text.replace("&amp;", "&")
    out = []
    for rx in (LINK_RE, TG_RE):
        for m in rx.finditer(text):
            out.append({"server": m.group(1), "port": int(m.group(2)), "secret": m.group(3).lower()})
    return out

def fetch_url(url):
    text = requests.get(url, timeout=30).text.strip()
    out = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for d in data:
                host = d.get("host") or d.get("server") or d.get("ip")
                sec, port = d.get("secret"), d.get("port")
                if host and sec and port:
                    out.append({"server": str(host), "port": int(port), "secret": str(sec).lower()})
            return out
    except Exception:
        pass
    text = text.replace("&amp;", "&")
    for rx in (LINK_RE, TG_RE):
        for m in rx.finditer(text):
            out.append({"server": m.group(1), "port": int(m.group(2)), "secret": m.group(3).lower()})
    for m in LINE_RE.finditer(text):
        out.append({"server": m.group(1), "port": int(m.group(2)), "secret": m.group(3).lower()})
    return out

def gather():
    src = STORE.data["sources"]
    items = []
    for url in src["urls"]:
        try:
            items += fetch_url(url)
        except Exception as e:
            log.warning(f"url err: {e}")
    for ch in src["channels"]:
        try:
            items += fetch_channel(ch)
        except Exception as e:
            log.warning(f"channel err: {e}")
    uniq = {}
    for p in items:
        k = (p["server"], p["port"])
        if k not in uniq:
            uniq[k] = p
    return list(uniq.values())

# ──────────── تست لایه ۱: TCP ────────────
def tcp_ping(host, port):
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None

def tcp_one(p):
    ms = tcp_ping(p["server"], p["port"])
    if ms is None:
        return None
    return {**p, "latency": ms, "flag": "🌐", "country": "", "deep": False}

# ──────────── تست لایه ۲: دست‌دهی واقعی MTProto ────────────
def deep_check(host, port, secret_hex):
    try:
        secret = bytes.fromhex(secret_hex)
    except Exception:
        return None
    if not secret or len(secret) < 16:
        return None
    if secret[:1] == b"\xEE":
        return None  # fakeTLS — فقط TCP
    if secret[:1] == b"\xDD":
        secret = secret[1:]
    secret = secret[:16]
    init = bytearray(os.urandom(64))
    init[0:16] = secret
    init[56:60] = b"\xEF\xEF\xEF\xEF"
    c2s = AES.new(bytes(init[8:40]), AES.MODE_CTR, nonce=b"", initial_value=bytes(init[40:56]))
    rev = bytes(init[8:56])[::-1]
    s2c = AES.new(rev[:32], AES.MODE_CTR, nonce=b"", initial_value=rev[32:48])
    try:
        s = socket.create_connection((host, port), timeout=DEEP_TIMEOUT)
        s.settimeout(DEEP_TIMEOUT)
        s.sendall(bytes(init[:56]) + c2s.encrypt(bytes(init[56:])))
        t0 = time.monotonic()
        nonce = os.urandom(16)
        inner = b"\x87\x07\x46\x60" + nonce  # req_pq
        msg_id = struct.pack("<q", (int(time.time()) << 32) | 1)
        plain = b"\x00" * 8 + msg_id + struct.pack("<I", len(inner)) + inner
        frame = b"\xEF" + bytes([len(plain)])
        s.sendall(c2s.encrypt(frame))
        buf = b""
        while time.monotonic() - t0 < DEEP_TIMEOUT and len(buf) < 1024:
            try:
                chunk = s.recv(512)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += s2c.decrypt(chunk)
            if b"\x63\x24\x16\x05" in buf:  # resPQ → پروکسی واقعاً زنده است
                ms = round((time.monotonic() - t0) * 1000)
                s.close()
                return ms
        s.close()
    except Exception:
        return None
    return None

def deep_one(c):
    ms = deep_check(c["server"], c["port"], c["secret"])
    if ms is None:
        return None
    return {**c, "latency": ms, "deep": True}

# ──────────── حلقه اصلی ────────────
def refresh_loop():
    while True:
        items = gather()
        with LOCK:
            S["fetched"] = len(items)
        log.info(f"gathered: {len(items)}")
        batch = items[:MAX_TO_TEST]
        tcp = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for r in pool.map(tcp_one, batch):
                if r:
                    tcp.append(r)
        tcp.sort(key=lambda c: c["latency"])
        with LOCK:
            S["tcp"] = len(tcp)
            S["tested"] = len(batch)
        deep_ok = []
        cands = [c for c in tcp if not c["secret"].startswith("ee")][:DEEP_LIMIT]
        if cands:
            log.info(f"deep: {len(cands)}")
            with ThreadPoolExecutor(DEEP_WORKERS) as pool:
                for r in pool.map(deep_one, cands):
                    if r:
                        deep_ok.append(r)
        deep_ok.sort(key=lambda c: c["latency"])
        deep_keys = {(c["server"], c["port"]) for c in deep_ok}
        rest = [c for c in tcp if (c["server"], c["port"]) not in deep_keys][:200]
        final = deep_ok + rest
        geo_batch(final)
        with LOCK:
            S["good"], S["last"] = final, datetime.now()
        log.info(f"final: {len(final)} (deep: {len(deep_ok)})")
        time.sleep(REFRESH_EVERY)
