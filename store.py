# -*- coding: utf-8 -*-
# HiVo Proxies — حافظه دائمی
import base64, json, logging, os, threading, time
from datetime import datetime

import requests

log = logging.getLogger("hivo.store")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = f"https://api.github.com/repos/{REPO}/contents/data/bot.json"
HDRS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


class Store:
    def __init__(self):
        self.data = {"users": {}, "admin": None,
                     "totals": {"files": 0, "proxies": 0},
                     "premium": [],
                     "sources": {"channels": [], "urls": ["https://mtpro.xyz/api/?type=mtproto"]},
                     "settings": {"lock_on": False, "lock_channel": "", "welcome": ""}}
        self._sha = None
        self._dirty = False
        self._lock = threading.Lock()

    def load(self):
        if not REPO or not TOKEN:
            return
        try:
            r = requests.get(API, headers=HDRS, timeout=30)
            if r.status_code == 200:
                self._sha = r.json().get("sha")
                d = json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore"))
                if isinstance(d, dict):
                    self.data.update(d)
                self.data.setdefault("users", {})
                self.data.setdefault("premium", [])
                self.data.setdefault("totals", {"files": 0, "proxies": 0})
                self.data.setdefault("sources", {"channels": [], "urls": ["https://mtpro.xyz/api/?type=mtproto"]})
                self.data.setdefault("settings", {})
                for k, v in {"lock_on": False, "lock_channel": "", "welcome": ""}.items():
                    self.data["settings"].setdefault(k, v)
                log.info(f"store: {len(self.data['users'])} users")
        except Exception as e:
            log.warning(f"store load: {e}")

    def save(self):
        if not REPO or not TOKEN:
            return False
        content = base64.b64encode(json.dumps(self.data, ensure_ascii=False).encode()).decode()
        payload = {"message": "update data", "content": content}
        if self._sha:
            payload["sha"] = self._sha
        try:
            r = requests.put(API, headers=HDRS, json=payload, timeout=30)
            if r.status_code in (200, 201):
                self._sha = r.json()["content"]["sha"]
                with self._lock:
                    self._dirty = False
                return True
            if r.status_code == 409:
                rr = requests.get(API, headers=HDRS, timeout=30)
                if rr.status_code == 200:
                    self._sha = rr.json().get("sha")
                    payload["sha"] = self._sha
                    r = requests.put(API, headers=HDRS, json=payload, timeout=30)
                    if r.status_code in (200, 201):
                        self._sha = r.json()["content"]["sha"]
                        with self._lock:
                            self._dirty = False
                        return True
        except Exception as e:
            log.warning(f"store save: {e}")
        return False

    def touch(self, user_id, first_name="", username=""):
        with self._lock:
            u = self.data["users"].setdefault(str(user_id), {
                "name": first_name, "user": username,
                "joined": datetime.now().isoformat(timespec="seconds"),
                "count": 0, "last": None})
            u["name"] = first_name or u.get("name", "")
            u["user"] = username or u.get("user", "")
            u["count"] += 1
            u["last"] = datetime.now().isoformat(timespec="seconds")
            if self.data.get("admin") is None:
                self.data["admin"] = str(user_id)
            self._dirty = True

    def set_admin(self, user_id):
        with self._lock:
            self.data["admin"] = str(user_id)
            self._dirty = True

    def is_admin(self, user_id):
        return self.data.get("admin") == str(user_id)

    def users(self):
        return self.data.get("users", {})

    def add_totals(self, files=0, proxies=0):
        with self._lock:
            self.data["totals"]["files"] += files
            self.data["totals"]["proxies"] += proxies
            self._dirty = True

    def premium(self):
        return self.data.get("premium", [])

    def add_premium(self, item):
        with self._lock:
            key = (item["server"], item["port"], item["secret"])
            for p in self.data["premium"]:
                if (p["server"], p["port"], p["secret"]) == key:
                    return False
            self.data["premium"].append(item)
            self._dirty = True
            return True

    def clear_premium(self):
        with self._lock:
            n = len(self.data["premium"])
            self.data["premium"] = []
            self._dirty = True
            return n

    def add_source(self, kind, value):
        with self._lock:
            if value not in self.data["sources"][kind]:
                self.data["sources"][kind].append(value)
                self._dirty = True
                return True
            return False

    def reset_sources(self):
        with self._lock:
            self.data["sources"] = {"channels": [], "urls": ["https://mtpro.xyz/api/?type=mtproto"]}
            self._dirty = True

    def set_setting(self, key, value):
        with self._lock:
            self.data["settings"][key] = value
            self._dirty = True

    def autosave_loop(self):
        while True:
            time.sleep(180)
            with self._lock:
                dirty = self._dirty
            if dirty:
                self.save()


STORE = Store()
