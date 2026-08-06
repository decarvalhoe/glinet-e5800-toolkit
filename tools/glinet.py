#!/usr/bin/env python3
"""
glinet.py - client CLI pour routeurs GL.iNet firmware 4.x (JSON-RPC /rpc).

Zero dependance : stdlib uniquement (sha256-crypt reimplemente, pas de module
`crypt` sur Windows).

  python glinet.py login
  python glinet.py call system get_info
  python glinet.py call wifi get_config
  python glinet.py call modem get_status
  python glinet.py call firewall add_port_forward '{"name":"ssh","proto":"tcp","src":"wan","src_dport":"2222","dest":"lan","dest_ip":"192.168.8.50","dest_port":22}'
  python glinet.py api wg          # cherche dans l'index des methodes
  python glinet.py raw '{"jsonrpc":"2.0","id":1,"method":"call","params":["SID","system","get_info",{}]}'

Mot de passe : variable d'env GLINET_PASSWORD, sinon prompt masque.
Le sid est cache dans ~/.glinet_session (chmod 600 sur POSIX).
"""

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = os.environ.get("GLINET_HOST", "192.168.8.1")
DEFAULT_USER = os.environ.get("GLINET_USER", "root")
SESSION_FILE = os.path.join(os.path.expanduser("~"), ".glinet_session")
_HERE = os.path.dirname(os.path.abspath(__file__))
# Index cherche a cote du script, puis dans ../api/ (disposition du depot).
API_INDEX_CANDIDATES = [
    os.path.join(_HERE, "glinet-api-index.json"),
    os.path.join(_HERE, os.pardir, "api", "glinet-api-index.json"),
]
API_INDEX_LIVE_CANDIDATES = [
    os.path.join(_HERE, "glinet-api-live.json"),
    os.path.join(_HERE, os.pardir, "api", "glinet-api-live.json"),
]

# --------------------------------------------------------------------------
# sha256-crypt / sha512-crypt / md5-crypt  (spec Ulrich Drepper)
# --------------------------------------------------------------------------
_B64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _b64_from_24bit(b2, b1, b0, n):
    w = (b2 << 16) | (b1 << 8) | b0
    return "".join(_B64[(w >> (6 * i)) & 0x3F] for i in range(n))


def _shacrypt(password, salt, hasher, digest_len, order, rounds=5000):
    pw = password.encode()
    sa = salt.encode()[:16]

    b = hasher(pw + sa + pw).digest()

    ctx = hasher(pw + sa)
    ctx.update(b * (len(pw) // digest_len))
    ctx.update(b[: len(pw) % digest_len])
    n = len(pw)
    while n:
        ctx.update(b if n & 1 else pw)
        n >>= 1
    a = ctx.digest()

    dp = hasher(pw * len(pw)).digest()
    p = (dp * (len(pw) // digest_len + 1))[: len(pw)]

    ds = hasher(sa * (16 + a[0])).digest()
    s = (ds * (len(sa) // digest_len + 1))[: len(sa)]

    c = a
    for i in range(rounds):
        ctx = hasher()
        ctx.update(p if i & 1 else c)
        if i % 3:
            ctx.update(s)
        if i % 7:
            ctx.update(p)
        ctx.update(c if i & 1 else p)
        c = ctx.digest()

    out = "".join(_b64_from_24bit(c[x], c[y], c[z], 4) for x, y, z in order[:-1])
    last = order[-1]
    if len(last) == 3:
        out += _b64_from_24bit(c[last[0]], c[last[1]], c[last[2]], 4)
    elif len(last) == 2:
        out += _b64_from_24bit(0, c[last[0]], c[last[1]], 3)
    else:
        out += _b64_from_24bit(0, 0, c[last[0]], 2)
    return out


_SHA256_ORDER = [
    (0, 10, 20), (21, 1, 11), (12, 22, 2), (3, 13, 23), (24, 4, 14),
    (15, 25, 5), (6, 16, 26), (27, 7, 17), (18, 28, 8), (9, 19, 29), (31, 30),
]
_SHA512_ORDER = [
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4), (47, 5, 26),
    (6, 27, 48), (28, 49, 7), (50, 8, 29), (9, 30, 51), (31, 52, 10), (53, 11, 32),
    (12, 33, 54), (34, 55, 13), (56, 14, 35), (15, 36, 57), (37, 58, 16), (59, 17, 38),
    (18, 39, 60), (40, 61, 19), (62, 20, 41), (63,),
]


def _md5crypt(password, salt):
    pw, sa = password.encode(), salt.encode()[:8]
    b = hashlib.md5(pw + sa + pw).digest()
    ctx = hashlib.md5(pw + b"$1$" + sa)
    ctx.update((b * (len(pw) // 16 + 1))[: len(pw)])
    n = len(pw)
    while n:
        ctx.update(b"\0" if n & 1 else pw[:1])
        n >>= 1
    c = ctx.digest()
    for i in range(1000):
        x = hashlib.md5()
        x.update(pw if i & 1 else c)
        if i % 3:
            x.update(sa)
        if i % 7:
            x.update(pw)
        x.update(c if i & 1 else pw)
        c = x.digest()
    order = [(0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)]
    out = "".join(_b64_from_24bit(c[x], c[y], c[z], 4) for x, y, z in order)
    return out + _b64_from_24bit(0, 0, c[11], 2)


def unix_crypt(password, salt, alg):
    """Retourne le hash complet '$alg$salt$digest' comme crypt(3)."""
    alg = str(alg)
    if alg == "1":
        return "$1$%s$%s" % (salt[:8], _md5crypt(password, salt))
    if alg == "5":
        return "$5$%s$%s" % (salt[:16], _shacrypt(password, salt, hashlib.sha256, 32, _SHA256_ORDER))
    if alg == "6":
        return "$6$%s$%s" % (salt[:16], _shacrypt(password, salt, hashlib.sha512, 64, _SHA512_ORDER))
    raise ValueError("algorithme crypt non supporte: %s" % alg)


# --------------------------------------------------------------------------
# Client JSON-RPC
# --------------------------------------------------------------------------
class GlinetError(Exception):
    pass


HINT = (
    "Aucun mot de passe fourni.\n"
    "  bash        : GLINET_PASSWORD='...' python glinet.py login\n"
    "  PowerShell  : $env:GLINET_PASSWORD='...'; python glinet.py login\n"
    "  pipe        : echo 'monpass' | python glinet.py login\n"
    "  ou lance la commande dans un terminal ou tu peux vraiment taper."
)


def _read_password(user, host):
    """Ne jamais bloquer : ni sans TTY, ni sur un pty sans humain derriere."""
    if not sys.stdin.isatty():
        pw = sys.stdin.readline().rstrip("\r\n")
        return pw if pw else sys.exit(HINT)

    # Un pty peut exister sans personne pour taper (Git Bash lance depuis un
    # agent, CI...). On borne l'attente : le thread est daemon, donc meme
    # bloque sur read() il n'empeche pas le process de sortir.
    import threading

    timeout = float(os.environ.get("GLINET_PROMPT_TIMEOUT", "60"))
    box = []

    def ask():
        try:
            box.append(getpass.getpass("Mot de passe admin %s@%s : " % (user, host)))
        except Exception:
            pass

    t = threading.Thread(target=ask, daemon=True)
    t.start()
    t.join(timeout)
    if box and box[0]:
        return box[0]
    sys.exit("\nPas de saisie apres %gs.\n%s" % (timeout, HINT))


class Glinet:
    def __init__(self, host=DEFAULT_HOST, user=DEFAULT_USER, scheme="http", timeout=20):
        self.url = "%s://%s/rpc" % (scheme, host)
        self.host = host
        self.user = user
        self.timeout = timeout
        self.sid = None
        self._id = 0

    # -- transport ---------------------------------------------------------
    def _post(self, payload):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.url, data=data,
            headers={"Content-Type": "application/json", "User-Agent": "glinet-cli/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.URLError as e:
            raise GlinetError("connexion %s impossible: %s" % (self.url, e))

    def rpc(self, method, params):
        self._id += 1
        res = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if "error" in res:
            raise GlinetError(json.dumps(res["error"], ensure_ascii=False))
        return res.get("result")

    # -- auth --------------------------------------------------------------
    def challenge(self):
        return self.rpc("challenge", {"username": self.user})

    def login(self, password):
        ch = self.challenge()
        cipher = unix_crypt(password, ch["salt"], ch.get("alg", 5))
        material = "%s:%s:%s" % (self.user, cipher, ch["nonce"])
        method = (ch.get("hash-method") or "md5").lower().replace("-", "")
        digest = getattr(hashlib, method)(material.encode()).hexdigest()
        res = self.rpc("login", {"username": self.user, "hash": digest})
        self.sid = res["sid"]
        return res

    def alive(self):
        if not self.sid:
            return False
        try:
            self.rpc("alive", {"sid": self.sid})
            return True
        except GlinetError:
            return False

    # -- appels ------------------------------------------------------------
    def call(self, module, method, params=None):
        return self.rpc("call", [self.sid, module, method, params or {}])

    # -- session persistee -------------------------------------------------
    def save(self):
        with open(SESSION_FILE, "w") as f:
            json.dump({"host": self.host, "user": self.user, "sid": self.sid}, f)
        if os.name == "posix":
            os.chmod(SESSION_FILE, 0o600)

    def load(self):
        try:
            with open(SESSION_FILE) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        if d.get("host") != self.host or d.get("user") != self.user:
            return False
        self.sid = d.get("sid")
        return bool(self.sid)

    def ensure_session(self, password=None):
        if self.load() and self.alive():
            return
        pw = password or os.environ.get("GLINET_PASSWORD")
        if not pw:
            pw = _read_password(self.user, self.host)
        self.login(pw)
        self.save()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


def _load_first(candidates):
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def cmd_api(args):
    """Recherche dans l'index. L'index 'live' (extrait du firmware) fait foi pour
    l'existence d'une methode ; l'ancien index n'apporte plus que les parametres."""
    live = _load_first(API_INDEX_LIVE_CANDIDATES)
    old = _load_first(API_INDEX_CANDIDATES) or []
    if live is None and not old:
        sys.exit("aucun index trouve (glinet-api-live.json / glinet-api-index.json)")

    params = {}
    for e in old:
        params[(e["mod"], e["method"])] = e.get("params") or ""

    if live is not None:
        entries = [(m["mod"], meth) for m in live for meth in m["methods"]]
        source = "firmware"
    else:
        entries = [(e["mod"], e["method"]) for e in old]
        source = "index 2023 (perime)"

    q = (args.query or "").lower()
    hits = [(m, me) for m, me in entries if q in m.lower() or q in me.lower()]

    cur = None
    for m, me in hits:
        if m != cur:
            cur = m
            print("\n== %s" % m)
        print("   %-28s %s" % (me, params.get((m, me), "")))
    print("\n%d methode(s)  [source: %s]" % (len(hits), source))


def main():
    p = argparse.ArgumentParser(description="Client CLI GL.iNet firmware 4.x")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--https", action="store_true", help="utiliser https")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="s'authentifier et cacher le sid")

    c = sub.add_parser("call", help="appeler <module> <methode> [params-json]")
    c.add_argument("module")
    c.add_argument("method")
    c.add_argument("params", nargs="?", default="{}")

    r = sub.add_parser("raw", help="envoyer un payload JSON-RPC brut")
    r.add_argument("payload")

    a = sub.add_parser("api", help="chercher dans l'index des 313 methodes")
    a.add_argument("query", nargs="?", default="")

    args = p.parse_args()

    if args.cmd == "api":
        return cmd_api(args)

    g = Glinet(args.host, args.user, "https" if args.https else "http")

    if args.cmd == "login":
        g.ensure_session()
        return _out({"sid": g.sid, "host": g.host, "cache": SESSION_FILE})

    g.ensure_session()

    if args.cmd == "call":
        try:
            params = json.loads(args.params)
        except ValueError as e:
            sys.exit("params JSON invalide: %s" % e)
        return _out(g.call(args.module, args.method, params))

    if args.cmd == "raw":
        payload = json.loads(args.payload)
        payload = json.loads(json.dumps(payload).replace("SID", g.sid))
        return _out(g._post(payload))


if __name__ == "__main__":
    try:
        main()
    except GlinetError as e:
        sys.exit("erreur: %s" % e)
    except KeyboardInterrupt:
        sys.exit(130)
