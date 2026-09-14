# -*- coding: utf-8 -*-
# HiVo Proxies — Store
import base64, json, logging, os, threading, time
from datetime import datetime

import requests

log = logging.getLogger("hivo.store")

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
MAX_USERS = 3000
MAX_USER_VOTES = 300

DEFAULTS = {
    "users": {}, "admin": None,
    "totals": {"files": 0, "proxies": 0},
    "premium": [], "votes": {}, "uvotes": {}, "sources": [],
    "settings": {"lock_on": False, "lock_channel": "", "welcome": ""},
}


class GitHubJSONBackend:
    def __init__(self):
        self.api = "https://api.github.com/repos/" + REPO + "/contents/data/bot.json"
        self.headers = {"Authorization": "Bearer " + TOKEN,
                        "Accept": "application/vnd.github+json"}

    @property
    def available(self):
        return bool(REPO and TOKEN)

    def load(self):
        r = requests.get(self.api, headers=self.headers, timeout=30)
        if r.status_code != 200:
            return None, None
        j = r.json()
        data = json.loads(base64.b64decode(j.get("content", "")).decode("utf-8", "ignore"))
        return data, j.get("sha")

    def save(self, data, sha):
        content = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
        payload = {"message": "update bot data", "content": content}
        if sha:
            payload["sha"] = sha
        r = requests.put(self.api, headers=self.headers, json=payload, timeout=30)
        if r.status_code in (200, 201):
            return r.json()["content"]["sha"]
        for _ in range(2):
            if r.status_code != 409:
                break
            rr = requests.get(self.api, headers=self.headers, timeout=30)
            if rr.status_code == 200:
                payload["sha"] = rr.json().get("sha")
                r = requests.put(self.api, headers=self.headers, json=payload, timeout=30)
                if r.status_code in (200, 201):
                    return r.json()["content"]["sha"]
        return None


def _copy(v):
    return json.loads(json.dumps(v))


class Store:
    def __init__(self):
        self.backend = GitHubJSONBackend()
        self.data = _copy(DEFAULTS)
        self._sha = None
        self._dirty = False
        self._lock = threading.RLock()

    def load(self):
        if not self.backend.available:
            log.warning("store: memory-only")
            return
        try:
            data, sha = self.backend.load()
            if isinstance(data, dict):
                with self._lock:
                    for k, v in DEFAULTS.items():
                        if not isinstance(data.get(k), type(v)) or data.get(k) is None:
                            data[k] = _copy(v)
                    for k, v in DEFAULTS["settings"].items():
                        data["settings"].setdefault(k, v)
                    self.data = data
                    self._sha = sha
                log.info("store loaded")
        except Exception as e:
            log.warning("store load: " + str(e))

    def save(self):
        with self._lock:
            if not self.backend.available:
                return False
            snapshot = _copy(self.data)
            sha = self.backend.save(snapshot, self._sha)
            if sha:
                self._sha = sha
                self._dirty = False
                return True
            return False

    def autosave_loop(self):
        while True:
            time.sleep(180)
            with self._lock:
                dirty = self._dirty
            if dirty:
                self.save()

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
            if len(self.data["users"]) > MAX_USERS:
                old = sorted(self.data["users"].items(), key=lambda kv: kv[1].get("last") or "")
                for uid, _ in old[:len(self.data["users"]) - MAX_USERS]:
                    del self.data["users"][uid]
            self._dirty = True

    def set_admin(self, user_id):
        with self._lock:
            self.data["admin"] = str(user_id)
            self._dirty = True
        self.save()

    def is_admin(self, user_id):
        with self._lock:
            return self.data.get("admin") == str(user_id)

    def users(self):
        with self._lock:
            return _copy(self.data.get("users", {}))

    def add_totals(self, files=0, proxies=0):
        with self._lock:
            self.data["totals"]["files"] += files
            self.data["totals"]["proxies"] += proxies
            self._dirty = True

    def premium(self):
        with self._lock:
            return list(self.data.get("premium", []))

    def add_premium(self, uris):
        with self._lock:
            before = len(self.data["premium"])
            for u in uris:
                if u not in self.data["premium"]:
                    self.data["premium"].append(u)
            added = len(self.data["premium"]) - before
            self._dirty = True
        self.save()
        return added

    def clear_premium(self):
        with self._lock:
            n = len(self.data["premium"])
            self.data["premium"] = []
            self._dirty = True
        self.save()
        return n

    def vote(self, user_id, fhash, host, val):
        with self._lock:
            v = self.data["votes"].setdefault(fhash, {"host": host, "up": 0, "down": 0})
            uv = self.data["uvotes"].setdefault(str(user_id), {})
            prev = uv.get(fhash)
            if prev == val:
                return "same"
            if prev == 1:
                v["up"] = max(0, v["up"] - 1)
            elif prev == -1:
                v["down"] = max(0, v["down"] - 1)
            uv[fhash] = val
            if val == 1:
                v["up"] += 1
            else:
                v["down"] += 1
            if len(uv) > MAX_USER_VOTES:
                for k in list(uv.keys())[:-MAX_USER_VOTES]:
                    del uv[k]
            self._dirty = True
            return "changed" if prev is not None else "added"

    def get_vote_host(self, fhash):
        with self._lock:
            v = self.data.get("votes", {}).get(fhash)
            return v.get("host") if v else None

    def vote_totals(self):
        with self._lock:
            up = sum(v.get("up", 0) for v in self.data.get("votes", {}).values())
            down = sum(v.get("down", 0) for v in self.data.get("votes", {}).values())
            return up, down

    def sources(self):
        with self._lock:
            return list(self.data.get("sources", []))

    def add_source(self, url):
        with self._lock:
            lst = self.data.setdefault("sources", [])
            if url in lst:
                return False
            lst.append(url)
            self._dirty = True
        self.save()
        return True

    def remove_source(self, url):
        with self._lock:
            lst = self.data.setdefault("sources", [])
            if url in lst:
                lst.remove(url)
                self._dirty = True
            else:
                return False
        self.save()
        return True

    def reset_sources(self):
        with self._lock:
            self.data["sources"] = []
            self._dirty = True
        self.save()

    def set_setting(self, key, value):
        with self._lock:
            self.data["settings"][key] = value
            self._dirty = True
        self.save()


STORE = Store()
