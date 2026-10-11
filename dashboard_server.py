# -*- coding: utf-8 -*-
"""
MAHIR v3.0 — Professional Web Dashboard
Embedded Async Web Server (aiohttp) — Single File Edition

5 Operation Modes:
  1. Solo BR
  2. Team Mode 4-Bot
  3. Auto Create + Bio + AUTO (BR<3 → LW 3+)
  4. Auto Create + Bio + Guild Request + BR
  5. Account Management
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web


# ============================================================
#  EXP TABLE + LEVEL CALCULATION
# ============================================================

EXP_TABLE: Dict[int, int] = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
    16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
    23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
    30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
    37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
    51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
    58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
    70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
    76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
    82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
    94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884
}


def calculate_level_progress(level: int, current_exp: int) -> Dict[str, Any]:
    level = max(1, level)
    next_level = min(100, level + 1)
    base_exp = EXP_TABLE.get(level, 0)
    target_exp = EXP_TABLE.get(next_level, base_exp + 50000)

    needed_for_level = max(1, target_exp - base_exp)
    earned_in_level = max(0, current_exp - base_exp)
    remaining_exp = max(0, target_exp - current_exp)
    progress_pct = min(100.0, max(0.0, (earned_in_level / needed_for_level) * 100.0))

    return {
        "next_level": next_level,
        "base_exp": base_exp,
        "target_exp": target_exp,
        "needed_for_level": needed_for_level,
        "earned_in_level": earned_in_level,
        "remaining_exp": remaining_exp,
        "progress_pct": round(progress_pct, 1)
    }


# ============================================================
#  BOT STATE
# ============================================================

class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_token_map: Dict[str, str] = {}
        self.auth_to_game_id: Dict[str, str] = {}
        self.game_to_auth_id: Dict[str, str] = {}
        self.paused_accounts: set = set()
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.active_writers: Dict[str, set] = {}
        self.active_mode: str = "IDLE"
        self.creating: bool = False
        self.create_progress: List[str] = []

    def register_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str not in self.active_writers:
            self.active_writers[uid_str] = set()
        self.active_writers[uid_str].add(writer)

    def unregister_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str in self.active_writers:
            self.active_writers[uid_str].discard(writer)
            if not self.active_writers[uid_str]:
                self.active_writers.pop(uid_str, None)

    def close_writers_for_account(self, uid: str):
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id:
            candidates.add(str(self.auth_to_game_id[uid_str]))
        if uid_str in self.game_to_auth_id:
            candidates.add(str(self.game_to_auth_id[uid_str]))
        if uid_str in self.account_token_map:
            mapped = self.account_token_map[uid_str]
            candidates.add(str(mapped))
            candidates.add(str(mapped)[:16])
        for c in list(candidates):
            writers = list(self.active_writers.get(c, []))
            for w in writers:
                try:
                    if hasattr(w, "close"):
                        if hasattr(w, "is_closing"):
                            if not w.is_closing():
                                w.close()
                        else:
                            w.close()
                except Exception:
                    pass
            self.active_writers.pop(c, None)

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": str(uid) if uid else None
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, token: Optional[str] = None, auth_uid: Optional[str] = None,
                         mode: str = "AUTO"):
        uid_str = str(uid)
        auth_uid_str = str(auth_uid) if auth_uid else self.game_to_auth_id.get(uid_str, "")
        if auth_uid_str:
            self.auth_to_game_id[auth_uid_str] = uid_str
            self.game_to_auth_id[uid_str] = auth_uid_str
            self.account_token_map[auth_uid_str] = uid_str
            self.account_token_map[uid_str] = auth_uid_str
        if token:
            self.account_token_map[uid_str] = token
            self.account_token_map[token[:16]] = uid_str
            if auth_uid_str:
                self.account_token_map[auth_uid_str] = token

        prog = calculate_level_progress(level or 1, exp)
        lvl_val = level or 1

        if mode == "LONE_WOLF":
            acc_mode = "LONE_WOLF"
            acc_mode_label = "Lone Wolf (Manual)"
        elif mode == "BR":
            acc_mode = "BR"
            acc_mode_label = "Battle Royale (Manual)"
        else:
            acc_mode = "AUTO"
            acc_mode_label = "AUTO → BR (Lvl < 3)" if lvl_val < 3 else "AUTO → LW (Lvl 3+)"

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "auth_uid": auth_uid_str or "",
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": lvl_val,
                "next_level": prog["next_level"],
                "mode": acc_mode,
                "mode_label": acc_mode_label,
                "selected_mode": mode,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "remaining_exp": prog["remaining_exp"],
                "target_exp": prog["target_exp"],
                "needed_for_level": prog["needed_for_level"],
                "earned_in_level": prog["earned_in_level"],
                "progress_pct": prog["progress_pct"],
                "likes": likes or 0,
                "status": "PAUSED" if self.is_paused(uid_str) else "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "token": token or "",
                "start_time": time.time(),
                "is_paused": self.is_paused(uid_str),
                "paused_at": time.time() if self.is_paused(uid_str) else None,
                "total_pause_duration": 0.0,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            if auth_uid_str: acc["auth_uid"] = auth_uid_str
            if nickname: acc["nickname"] = nickname
            if region: acc["region"] = region
            if level: acc["level"] = level
            if token: acc["token"] = token
            acc["selected_mode"] = mode
            acc["mode"] = acc_mode
            acc["mode_label"] = acc_mode_label
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["likes"] = likes
            if not acc.get("is_paused"):
                acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def get_account_uptime(self, uid_str: str) -> int:
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts:
                acc = self.accounts[mapped]
        if not acc:
            return 0
        start_t = acc.get("start_time", time.time())
        total_pause = acc.get("total_pause_duration", 0.0)
        if acc.get("is_paused") and acc.get("paused_at"):
            return max(0, int(acc["paused_at"] - start_t - total_pause))
        return max(0, int(time.time() - start_t - total_pause))

    def is_paused(self, uid: str) -> bool:
        uid_str = str(uid)
        if uid_str in self.paused_accounts: return True
        game_id = self.auth_to_game_id.get(uid_str)
        if game_id and game_id in self.paused_accounts: return True
        auth_uid = self.game_to_auth_id.get(uid_str)
        if auth_uid and auth_uid in self.paused_accounts: return True
        acc = self.accounts.get(uid_str) or (self.accounts.get(game_id) if game_id else None)
        if acc and acc.get("is_paused"): return True
        return False

    def toggle_pause(self, uid: str) -> bool:
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id: candidates.add(self.auth_to_game_id[uid_str])
        if uid_str in self.game_to_auth_id: candidates.add(self.game_to_auth_id[uid_str])

        target_acc = None
        target_key = uid_str
        for c in candidates:
            if c in self.accounts:
                target_acc = self.accounts[c]
                target_key = c
                break

        is_now_paused = not self.is_paused(uid_str)
        if is_now_paused:
            for c in candidates:
                self.paused_accounts.add(c)
                self.close_writers_for_account(c)
            if target_acc:
                target_acc["is_paused"] = True
                target_acc["paused_at"] = time.time()
                target_acc["status"] = "PAUSED"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"⏸ UID {target_key} ({nick}) PAUSED.", "warning", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try: asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, True))
                except Exception: pass
        else:
            for c in candidates: self.paused_accounts.discard(c)
            if target_acc:
                target_acc["is_paused"] = False
                if target_acc.get("paused_at"):
                    pause_dur = time.time() - target_acc["paused_at"]
                    target_acc["total_pause_duration"] = target_acc.get("total_pause_duration", 0.0) + pause_dur
                    target_acc["paused_at"] = None
                target_acc["status"] = "ONLINE"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"▶ UID {target_key} ({nick}) RESUMED.", "success", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try: asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, False))
                except Exception: pass
        return is_now_paused

    def toggle_pause_all(self) -> bool:
        any_active = any(not self.is_paused(k) for k in self.accounts.keys())
        for k in list(self.accounts.keys()):
            current_paused = self.is_paused(k)
            if any_active and not current_paused: self.toggle_pause(k)
            elif not any_active and current_paused: self.toggle_pause(k)
        return any_active

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            old_level = acc.get("level", 1)
            acc["current_exp"] = current_exp
            if level is not None and level > 0: acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])

            current_lvl = acc["level"]
            sel_mode = acc.get("selected_mode", "AUTO")
            if sel_mode == "LONE_WOLF":
                acc["mode"] = "LONE_WOLF"
                acc["mode_label"] = "Lone Wolf (Manual)"
            elif sel_mode == "BR":
                acc["mode"] = "BR"
                acc["mode_label"] = "Battle Royale (Manual)"
            else:
                acc["mode"] = "AUTO"
                acc["mode_label"] = "AUTO → BR (Lvl < 3)" if current_lvl < 3 else "AUTO → LW (Lvl 3+)"

            prog = calculate_level_progress(acc["level"], current_exp)
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["last_updated"] = time.strftime("%H:%M:%S")

            if old_level < 3 and current_lvl >= 3:
                self.log(f"🎉 LEVEL UP! UID {uid_str} ({acc['nickname']}) reached Level {current_lvl}!", "success", uid_str)

            diff = current_exp - old_exp
            if diff > 0:
                self.log(f"★ UID {uid_str} ({acc['nickname']}) gained +{diff:,} EXP | Level {acc['level']} [{acc['mode']}] ({prog['progress_pct']}% - {prog['remaining_exp']:,} EXP to Lvl {prog['next_level']})", "success", uid_str)
            self.recalc_totals()

    def get_account_level(self, uid: str) -> int:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts: acc = self.accounts[mapped]
        if acc: return int(acc.get("level", 1) or 1)
        return 1

    def get_account_mode(self, uid: str) -> str:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts: acc = self.accounts[mapped]
        if not acc: return "AUTO"
        sel_mode = acc.get("selected_mode", "AUTO")
        if sel_mode == "LONE_WOLF": return "LONE_WOLF"
        if sel_mode == "BR": return "BR"
        if acc.get("level", 1) < 3: return "BR"
        return "LONE_WOLF"

    def set_account_mode(self, uid: str, mode: str):
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id: candidates.add(str(self.auth_to_game_id[uid_str]))
        if uid_str in self.game_to_auth_id: candidates.add(str(self.game_to_auth_id[uid_str]))

        target_acc = None
        target_key = uid_str
        for c in candidates:
            if c in self.accounts:
                target_acc = self.accounts[c]
                target_key = c
                break

        if target_acc:
            target_acc["selected_mode"] = mode
            lvl = target_acc.get("level", 1)
            if mode == "LONE_WOLF":
                target_acc["mode"] = "LONE_WOLF"
                target_acc["mode_label"] = "Lone Wolf (Manual)"
            elif mode == "BR":
                target_acc["mode"] = "BR"
                target_acc["mode_label"] = "Battle Royale (Manual)"
            else:
                target_acc["mode"] = "AUTO"
                target_acc["mode_label"] = "AUTO → BR (Lvl < 3)" if lvl < 3 else "AUTO → LW (Lvl 3+)"
            target_acc["last_updated"] = time.strftime("%H:%M:%S")
            for c in candidates:
                creds = self.account_credentials.get(c)
                if creds: creds['mode'] = mode
            self.log(f"🎮 UID {target_key} mode changed to {mode}", "info", target_key)
        return target_acc is not None

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"⚔ Match #{self.accounts[uid_str]['matches_played']} finished for {self.accounts[uid_str]['nickname']} ({uid_str})", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ============================================================
#  EMBEDDED HTML DASHBOARD
# ============================================================

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>MAHIR v3.0 | FreeFire Command Center</title>

    <!-- ⭐ Favicon (gradient bolt) -->
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0%25' y1='0%25' x2='100%25' y2='100%25'%3E%3Cstop offset='0%25' stop-color='%23a855f7'/%3E%3Cstop offset='50%25' stop-color='%2300b3ff'/%3E%3Cstop offset='100%25' stop-color='%2300ffc8'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='100' height='100' rx='22' fill='url(%23g)'/%3E%3Ctext x='50' y='70' font-family='Arial' font-size='58' font-weight='900' fill='white' text-anchor='middle'%3E%E2%9A%A1%3C/text%3E%3C/svg%3E">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">

    <style>
        :root {
            --bg-base: #07060e;
            --bg-card: rgba(20, 16, 40, 0.82);
            --bg-card-hover: rgba(32, 24, 60, 0.94);
            --border-card: rgba(168, 85, 247, 0.18);
            --border-hover: rgba(0, 255, 200, 0.45);

            --accent-cyan: #00ffc8;
            --accent-blue: #00b3ff;
            --accent-purple: #a855f7;
            --accent-red: #ff2e63;
            --accent-amber: #ff9f1c;
            --accent-pink: #ec4899;

            --text-main: #f0f4ff;
            --text-muted: #9aa5c9;
            --text-dim: #6b739a;

            --shadow-card: 0 12px 32px -6px rgba(0, 0, 0, 0.75);
            --radius-lg: 20px;
            --radius-md: 14px;
            --radius-sm: 8px;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; -webkit-tap-highlight-color: transparent; }

        html, body { height: 100%; }

        body {
            background-color: var(--bg-base);
            background-image:
                radial-gradient(circle at 10% 12%, rgba(168, 85, 247, 0.18) 0%, transparent 46%),
                radial-gradient(circle at 88% 88%, rgba(0, 255, 200, 0.13) 0%, transparent 52%),
                radial-gradient(circle at 50% 50%, rgba(0, 179, 255, 0.08) 0%, transparent 62%),
                linear-gradient(180deg, #07060e 0%, #120e28 55%, #0a0818 100%);
            color: var(--text-main);
            min-height: 100vh;
            overflow-x: hidden;
            background-attachment: fixed;
        }

        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-size: 40px 40px;
            background-image:
                linear-gradient(to right, rgba(168, 85, 247, 0.03) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(0, 255, 200, 0.03) 1px, transparent 1px);
            pointer-events: none;
            z-index: 0;
        }

        .app-shell { position: relative; z-index: 1; max-width: 1520px; margin: 0 auto; padding: 22px; }

        .btn, .icon-btn, .btn-copy, .filter-btn, .console-pill, .toggle-btn,
        .btn-pause-all, .mobile-nav-item, .brand-logo, .stat-card, .acc-card,
        .form-control, .mode-select, .option-card, .bot-file-row {
            transition: transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1),
                        box-shadow 0.25s ease,
                        background 0.25s ease,
                        border-color 0.25s ease,
                        color 0.2s ease,
                        opacity 0.2s ease;
        }

        .btn:active, .icon-btn:active, .filter-btn:active,
        .console-pill:active, .toggle-btn:active, .btn-pause-all:active,
        .mobile-nav-item:active {
            transform: scale(0.92);
            transition: transform 0.08s ease;
        }

        .desktop-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 26px;
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: var(--radius-lg);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: var(--shadow-card);
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 14px;
        }

        .brand { display: flex; align-items: center; gap: 16px; }

        .brand-logo {
            width: 50px; height: 50px;
            background: linear-gradient(135deg, #a855f7 0%, #00b3ff 45%, #00ffc8 100%);
            border-radius: 14px;
            display: flex; align-items: center; justify-content: center;
            font-size: 24px; color: #fff;
            box-shadow: 0 0 22px rgba(168, 85, 247, 0.55), 0 0 36px rgba(0, 255, 200, 0.28);
            animation: pulse-glow 3s infinite alternate;
            cursor: pointer;
        }

        @keyframes pulse-glow {
            0% { box-shadow: 0 0 16px rgba(168, 85, 247, 0.45); }
            100% { box-shadow: 0 0 28px rgba(0, 255, 200, 0.55); }
        }

        .brand-title h1 {
            font-size: 22px; font-weight: 800; letter-spacing: -0.5px;
            background: linear-gradient(90deg, #ffffff 15%, #c084fc 55%, #00ffc8 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .brand-sub {
            display: flex; align-items: center; gap: 10px;
            font-size: 12.5px; color: var(--text-muted); margin-top: 3px;
            flex-wrap: wrap;
        }

        .badge-live {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(0, 255, 200, 0.12);
            border: 1px solid rgba(0, 255, 200, 0.35);
            color: var(--accent-cyan);
            padding: 3px 10px; border-radius: 20px;
            font-size: 10.5px; font-weight: 700; text-transform: uppercase;
        }

        .badge-mode {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(168, 85, 247, 0.15);
            border: 1px solid rgba(168, 85, 247, 0.45);
            color: #c084fc;
            padding: 3px 10px; border-radius: 20px;
            font-size: 10.5px; font-weight: 700; text-transform: uppercase;
        }

        .radar-dot { position: relative; width: 7px; height: 7px; background: var(--accent-cyan); border-radius: 50%; }
        .radar-dot::after {
            content: '';
            position: absolute;
            top: -4px; left: -4px; right: -4px; bottom: -4px;
            border: 2px solid var(--accent-cyan);
            border-radius: 50%;
            animation: radar-wave 1.6s ease-out infinite;
        }

        @keyframes radar-wave {
            0% { transform: scale(0.6); opacity: 1; }
            100% { transform: scale(2.2); opacity: 0; }
        }

        .header-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

        .btn {
            display: inline-flex; align-items: center; justify-content: center; gap: 8px;
            padding: 10px 16px; border-radius: var(--radius-md);
            font-size: 13px; font-weight: 600;
            cursor: pointer;
            border: 1px solid transparent;
            outline: none;
            user-select: none;
            white-space: nowrap;
        }

        .btn-primary {
            background: linear-gradient(135deg, #a855f7 0%, #00b3ff 55%, #00ffc8 100%);
            color: #071018; font-weight: 800;
            box-shadow: 0 4px 18px rgba(168, 85, 247, 0.4), 0 4px 14px rgba(0, 255, 200, 0.25);
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 26px rgba(168, 85, 247, 0.55), 0 6px 20px rgba(0, 255, 200, 0.35);
        }

        .btn-success {
            background: linear-gradient(135deg, #00b3ff 0%, #00ffc8 100%);
            color: #071018; font-weight: 800;
            box-shadow: 0 4px 18px rgba(0, 179, 255, 0.35);
        }
        .btn-success:hover { transform: translateY(-2px); box-shadow: 0 6px 26px rgba(0, 255, 200, 0.5); }

        .btn-warn {
            background: linear-gradient(135deg, #ff9f1c 0%, #ec4899 100%);
            color: #fff; font-weight: 800;
            box-shadow: 0 4px 18px rgba(255, 159, 28, 0.35);
        }
        .btn-warn:hover { transform: translateY(-2px); box-shadow: 0 6px 26px rgba(236, 72, 153, 0.5); }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(168, 85, 247, 0.25);
            color: var(--text-main);
        }
        .btn-secondary:hover { background: rgba(168, 85, 247, 0.12); border-color: var(--border-hover); }

        .stats-hero {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 22px;
        }

        .stat-card {
            background: linear-gradient(150deg, rgba(24, 18, 48, 0.9) 0%, rgba(14, 10, 32, 0.95) 100%);
            border: 1px solid rgba(168, 85, 247, 0.2);
            border-radius: 18px;
            padding: 16px 16px 14px 16px;
            backdrop-filter: blur(18px);
            box-shadow: 0 10px 28px -8px rgba(0, 0, 0, 0.7);
            position: relative;
            overflow: hidden;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            gap: 10px;
            min-height: 112px;
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0;
            width: 100%; height: 2px;
            background: transparent;
            transition: background 0.3s ease;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            right: -30px; bottom: -30px;
            width: 100px; height: 100px;
            border-radius: 50%;
            background: radial-gradient(circle, currentColor 0%, transparent 70%);
            opacity: 0.08;
            pointer-events: none;
        }

        .stat-card:hover {
            transform: translateY(-4px);
            border-color: var(--border-hover);
            box-shadow: 0 18px 40px -10px rgba(0, 255, 200, 0.3);
        }

        .stat-card.cyan::before { background: linear-gradient(90deg, #00ffc8, transparent); color: #00ffc8; }
        .stat-card.green::before { background: linear-gradient(90deg, #00ffc8, transparent); color: #00ffc8; }
        .stat-card.purple::before { background: linear-gradient(90deg, #a855f7, transparent); color: #a855f7; }
        .stat-card.amber::before { background: linear-gradient(90deg, #ff9f1c, transparent); color: #ff9f1c; }
        .stat-card.pink::before { background: linear-gradient(90deg, #ec4899, transparent); color: #ec4899; }

        .stat-card .stat-icon-wrap {
            width: 36px; height: 36px;
            border-radius: 10px;
            display: flex; align-items: center; justify-content: center;
            font-size: 15px;
            flex-shrink: 0;
        }

        .stat-card .stat-icon-wrap.cyan { background: rgba(0, 255, 200, 0.14); color: var(--accent-cyan); border: 1px solid rgba(0, 255, 200, 0.3); }
        .stat-card .stat-icon-wrap.green { background: rgba(0, 255, 200, 0.14); color: var(--accent-cyan); border: 1px solid rgba(0, 255, 200, 0.3); }
        .stat-card .stat-icon-wrap.purple { background: rgba(168, 85, 247, 0.15); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.35); }
        .stat-card .stat-icon-wrap.amber { background: rgba(255, 159, 28, 0.15); color: var(--accent-amber); border: 1px solid rgba(255, 159, 28, 0.35); }
        .stat-card .stat-icon-wrap.pink { background: rgba(236, 72, 153, 0.15); color: #f9a8d4; border: 1px solid rgba(236, 72, 153, 0.35); }

        .stat-card .stat-data {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }

        .stat-card .stat-data p {
            font-size: 10.5px;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.7px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .stat-card .stat-data h2 {
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.5px;
            color: #fff;
            font-family: 'JetBrains Mono', monospace;
            line-height: 1.1;
        }

        .options-bar {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 22px;
        }

        .option-card {
            background: linear-gradient(150deg, rgba(24, 18, 48, 0.9) 0%, rgba(14, 10, 32, 0.95) 100%);
            border: 1px solid rgba(168, 85, 247, 0.2);
            border-radius: 16px;
            padding: 16px;
            cursor: pointer;
            position: relative;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            gap: 10px;
            backdrop-filter: blur(14px);
            min-height: 175px;
        }

        .option-card:hover {
            transform: translateY(-5px);
            border-color: var(--border-hover);
            box-shadow: 0 18px 40px -8px rgba(0, 255, 200, 0.28);
        }

        .option-card .opt-num {
            position: absolute;
            top: 14px; right: 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px; font-weight: 800;
            color: var(--text-dim);
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(168, 85, 247, 0.2);
            padding: 2px 8px;
            border-radius: 8px;
            letter-spacing: 0.5px;
        }

        .option-card .opt-icon {
            width: 44px; height: 44px;
            border-radius: 13px;
            display: flex; align-items: center; justify-content: center;
            font-size: 19px;
            flex-shrink: 0;
        }

        .option-card.o1 .opt-icon { background: rgba(0, 179, 255, 0.14); color: #66d9ff; border: 1px solid rgba(0, 179, 255, 0.32); }
        .option-card.o2 .opt-icon { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.38); }
        .option-card.o3 .opt-icon { background: rgba(0, 255, 200, 0.13); color: var(--accent-cyan); border: 1px solid rgba(0, 255, 200, 0.32); }
        .option-card.o4 .opt-icon { background: rgba(255, 159, 28, 0.15); color: var(--accent-amber); border: 1px solid rgba(255, 159, 28, 0.38); }
        .option-card.o5 .opt-icon { background: rgba(236, 72, 153, 0.15); color: #f9a8d4; border: 1px solid rgba(236, 72, 153, 0.38); }

        .option-card h4 {
            font-size: 13.5px;
            font-weight: 800;
            color: #fff;
            line-height: 1.3;
            letter-spacing: -0.2px;
        }

        .option-card p {
            font-size: 11px;
            color: var(--text-muted);
            line-height: 1.5;
            flex: 1;
        }

        .option-card .opt-cta {
            display: inline-flex; align-items: center; gap: 5px;
            font-size: 10.5px; font-weight: 700;
            color: var(--accent-cyan);
            letter-spacing: 0.4px;
            text-transform: uppercase;
            margin-top: 2px;
        }

        .option-card .opt-cta i {
            font-size: 9px;
            transition: transform 0.2s ease;
        }

        .option-card:hover .opt-cta i { transform: translateX(4px); }

        .workspace-grid {
            display: grid;
            grid-template-columns: 1fr 470px;
            gap: 20px;
        }

        .panel-box {
            background: var(--bg-card);
            border: 1px solid var(--border-card);
            border-radius: var(--radius-lg);
            padding: 20px;
            backdrop-filter: blur(16px);
            box-shadow: var(--shadow-card);
            display: flex;
            flex-direction: column;
        }

        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(168, 85, 247, 0.12);
            flex-wrap: wrap;
            gap: 12px;
        }

        .panel-title { display: flex; align-items: center; gap: 12px; }
        .panel-title h3 { font-size: 17px; font-weight: 700; color: #fff; }

        .counter-pill {
            background: rgba(0, 255, 200, 0.13);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 255, 200, 0.25);
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11.5px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .filter-row {
            display: flex; align-items: center; justify-content: space-between;
            gap: 14px; margin-bottom: 16px; flex-wrap: wrap;
        }

        .search-box { flex: 1; min-width: 220px; position: relative; }

        .search-box i {
            position: absolute;
            left: 14px; top: 50%;
            transform: translateY(-50%);
            color: var(--text-dim);
            font-size: 13px;
        }

        .search-box input {
            width: 100%;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(168, 85, 247, 0.2);
            border-radius: var(--radius-md);
            padding: 9px 14px 9px 38px;
            color: #fff; font-size: 13px;
            outline: none;
            transition: all 0.2s;
        }

        .search-box input:focus {
            border-color: rgba(0, 255, 200, 0.55);
            background: rgba(0, 255, 200, 0.07);
            box-shadow: 0 0 12px rgba(0, 255, 200, 0.22);
        }

        .filter-tabs {
            display: flex; gap: 6px;
            background: rgba(0, 0, 0, 0.35);
            padding: 4px; border-radius: var(--radius-md);
            border: 1px solid rgba(168, 85, 247, 0.15);
        }

        .filter-btn {
            background: transparent; border: none;
            color: var(--text-muted);
            padding: 6px 12px; border-radius: 8px;
            font-size: 12px; font-weight: 600;
            cursor: pointer;
        }

        .filter-btn.active {
            background: rgba(0, 255, 200, 0.16);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 255, 200, 0.28);
        }

        .accounts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
            gap: 14px;
            max-height: 900px;
            overflow-y: auto;
            padding-right: 4px;
        }

        .accounts-grid::-webkit-scrollbar { width: 6px; }
        .accounts-grid::-webkit-scrollbar-thumb { background: rgba(168, 85, 247, 0.25); border-radius: 4px; }

        .acc-card {
            background: linear-gradient(160deg, rgba(20, 16, 40, 0.85) 0%, rgba(12, 10, 28, 0.9) 100%);
            border: 1px solid rgba(168, 85, 247, 0.18);
            border-radius: 16px;
            padding: 16px;
            position: relative;
            cursor: pointer;
            overflow: hidden;
        }

        .acc-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, #a855f7 0%, #00b3ff 50%, #00ffc8 100%);
            opacity: 0.35;
            transition: opacity 0.3s ease;
        }

        .acc-card:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-3px);
            box-shadow: 0 14px 36px -8px rgba(0, 255, 200, 0.25);
        }

        .acc-card:hover::before { opacity: 0.9; }

        .acc-header {
            display: flex; align-items: flex-start; justify-content: space-between;
            margin-bottom: 12px; gap: 12px;
        }

        .acc-identity { display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1; }

        .acc-avatar {
            width: 46px; height: 46px;
            border-radius: 13px;
            background: linear-gradient(135deg, #1a1438, #2a1e5a);
            display: flex; align-items: center; justify-content: center;
            font-size: 18px; color: var(--accent-cyan);
            border: 1px solid rgba(0, 255, 200, 0.3);
            position: relative;
            flex-shrink: 0;
        }

        .level-badge {
            position: absolute;
            bottom: -6px; right: -6px;
            background: #0f0a1f;
            border: 1px solid var(--accent-cyan);
            color: #fff;
            font-size: 10px; font-weight: 800;
            padding: 1px 5px;
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
        }

        .acc-details { min-width: 0; flex: 1; }
        .acc-details h4 {
            font-size: 14.5px; font-weight: 700; color: #fff;
            display: flex; align-items: center; gap: 7px; flex-wrap: wrap;
            line-height: 1.3;
        }

        .region-tag {
            background: rgba(0, 179, 255, 0.16);
            color: #66d9ff;
            border: 1px solid rgba(0, 179, 255, 0.35);
            padding: 1px 6px; border-radius: 5px;
            font-size: 9.5px; font-weight: 700;
            letter-spacing: 0.3px;
        }

        .acc-uid {
            font-size: 11px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
            margin-top: 4px;
            display: flex; align-items: center; gap: 6px;
            flex-wrap: wrap;
        }

        .btn-copy {
            background: transparent; border: none;
            color: var(--text-dim); cursor: pointer;
            font-size: 11px; padding: 2px 5px;
            border-radius: 4px;
        }
        .btn-copy:hover { color: var(--accent-cyan); background: rgba(0, 255, 200, 0.1); }

        .status-pill {
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 10px; font-weight: 700;
            padding: 4px 9px; border-radius: 20px;
            white-space: nowrap;
            flex-shrink: 0;
        }

        .status-pill.online { background: rgba(0, 255, 200, 0.12); color: var(--accent-cyan); border: 1px solid rgba(0, 255, 200, 0.32); }
        .status-pill.in_match { background: rgba(168, 85, 247, 0.14); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.45); animation: pulse-border 1.5s infinite alternate; }
        .status-pill.searching { background: rgba(0, 179, 255, 0.13); color: #66d9ff; border: 1px solid rgba(0, 179, 255, 0.38); }
        .status-pill.paused { background: rgba(255, 159, 28, 0.12); color: #ffb84d; border: 1px solid rgba(255, 159, 28, 0.42); }
        .status-pill.offline, .status-pill.error { background: rgba(255, 46, 99, 0.12); color: var(--accent-red); border: 1px solid rgba(255, 46, 99, 0.32); }

        @keyframes pulse-border {
            0% { border-color: rgba(168, 85, 247, 0.35); box-shadow: 0 0 6px rgba(168, 85, 247, 0.22); }
            100% { border-color: rgba(168, 85, 247, 0.95); box-shadow: 0 0 16px rgba(168, 85, 247, 0.5); }
        }

        .runtime-strip {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 13px;
            background: linear-gradient(90deg, rgba(0, 255, 200, 0.08) 0%, rgba(168, 85, 247, 0.08) 100%);
            border: 1px solid rgba(0, 255, 200, 0.22);
            border-radius: 12px;
            margin-bottom: 12px;
            gap: 10px;
            flex-wrap: wrap;
        }

        .runtime-strip .rt-left {
            display: flex; align-items: center; gap: 10px;
        }

        .runtime-strip .rt-icon {
            width: 30px; height: 30px;
            border-radius: 9px;
            background: rgba(0, 255, 200, 0.15);
            border: 1px solid rgba(0, 255, 200, 0.35);
            color: var(--accent-cyan);
            display: flex; align-items: center; justify-content: center;
            font-size: 13px;
            flex-shrink: 0;
        }

        .runtime-strip .rt-info { display: flex; flex-direction: column; gap: 1px; }
        .runtime-strip .rt-label {
            font-size: 9.5px; font-weight: 700; color: var(--text-dim);
            text-transform: uppercase; letter-spacing: 0.5px;
        }

        .runtime-strip .rt-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 15px; font-weight: 800;
            color: var(--accent-cyan);
            letter-spacing: 0.5px;
        }

        .runtime-strip .rt-minutes {
            display: flex; flex-direction: column; gap: 1px;
            align-items: flex-end;
        }

        .runtime-strip .rt-min-label {
            font-size: 9px; font-weight: 700; color: var(--text-dim);
            text-transform: uppercase; letter-spacing: 0.5px;
        }

        .runtime-strip .rt-min-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12.5px; font-weight: 800;
            color: #fff;
            background: rgba(0, 0, 0, 0.35);
            padding: 2px 9px;
            border-radius: 8px;
            border: 1px solid rgba(168, 85, 247, 0.3);
        }

        .exp-strip {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(168, 85, 247, 0.1);
            border-radius: 12px;
            padding: 10px 12px;
            margin-bottom: 12px;
        }

        .exp-col { display: flex; flex-direction: column; gap: 2px; }
        .exp-col span { font-size: 10px; color: var(--text-dim); text-transform: uppercase; font-weight: 600; letter-spacing: 0.4px; }
        .exp-col strong { font-size: 13px; font-weight: 700; color: #fff; font-family: 'JetBrains Mono', monospace; }
        .exp-gained-highlight { color: #00ffc8 !important; }

        .card-progress {
            margin-bottom: 12px;
            background: rgba(255, 255, 255, 0.02);
            padding: 10px 12px;
            border-radius: 12px;
            border: 1px solid rgba(168, 85, 247, 0.1);
        }

        .progress-header {
            display: flex; justify-content: space-between; align-items: center;
            font-size: 11px; margin-bottom: 8px; font-weight: 600;
            flex-wrap: wrap; gap: 6px;
        }

        .prog-level-tag { color: var(--text-main); display: flex; align-items: center; gap: 6px; font-size: 11px; }

        .prog-needed-badge {
            background: rgba(168, 85, 247, 0.16);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.35);
            padding: 2px 8px; border-radius: 20px;
            font-size: 10px; font-weight: 700;
        }

        .progress-track {
            height: 8px;
            background: rgba(0, 0, 0, 0.55);
            border-radius: 12px;
            overflow: hidden;
            position: relative;
            border: 1px solid rgba(168, 85, 247, 0.15);
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #00b3ff 0%, #00ffc8 25%, #a855f7 50%, #00ffc8 75%, #00b3ff 100%);
            background-size: 200% 100%;
            border-radius: 12px;
            transition: width 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
            animation: progressGlowShift 3s infinite linear;
            box-shadow: 0 0 14px rgba(0, 255, 200, 0.55);
        }

        @keyframes progressGlowShift {
            0% { background-position: 0% 50%; }
            100% { background-position: 200% 50%; }
        }

        .progress-sub {
            display: flex; justify-content: space-between;
            font-size: 10px; color: var(--text-dim); margin-top: 6px;
        }

        .prog-pct-pill {
            color: var(--accent-cyan);
            font-weight: 700;
            font-size: 10px;
            background: rgba(0, 255, 200, 0.10);
            padding: 1px 6px; border-radius: 8px;
            border: 1px solid rgba(0, 255, 200, 0.28);
        }

        .mode-selector-row {
            display: flex; align-items: center; gap: 8px;
            margin-bottom: 12px;
            padding: 7px 10px;
            background: rgba(0, 0, 0, 0.35);
            border-radius: 10px;
            border: 1px solid rgba(168, 85, 247, 0.15);
        }

        .mode-selector-row label {
            font-size: 10.5px; font-weight: 700;
            color: var(--text-dim);
            text-transform: uppercase;
            flex-shrink: 0;
            display: flex; align-items: center; gap: 5px;
        }

        .mode-select {
            flex: 1;
            background: rgba(20, 16, 40, 0.9);
            border: 1px solid rgba(168, 85, 247, 0.25);
            color: #fff;
            padding: 5px 9px;
            border-radius: 8px;
            font-size: 11.5px; font-weight: 600;
            cursor: pointer; outline: none;
        }

        .mode-select option { background: #0d0920; color: #fff; }

        .acc-footer {
            display: flex; align-items: center; justify-content: space-between;
            padding-top: 10px;
            border-top: 1px solid rgba(168, 85, 247, 0.1);
            font-size: 11px; color: var(--text-dim);
            flex-wrap: wrap; gap: 8px;
        }

        .acc-btns { display: flex; align-items: center; gap: 6px; }

        .icon-btn {
            width: 32px; height: 32px;
            border-radius: 9px;
            background: rgba(168, 85, 247, 0.08);
            border: 1px solid rgba(168, 85, 247, 0.2);
            color: var(--text-muted);
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            font-size: 12px;
        }

        .icon-btn:hover {
            background: rgba(0, 255, 200, 0.15);
            color: var(--accent-cyan);
            border-color: var(--accent-cyan);
        }

        .icon-btn.danger:hover {
            background: rgba(255, 46, 99, 0.15);
            color: var(--accent-red);
            border-color: var(--accent-red);
        }

        .icon-btn.btn-pause { color: #ffb84d; }
        .icon-btn.btn-pause:hover { background: rgba(255, 159, 28, 0.18); color: #ffb84d; border-color: #ffb84d; }
        .icon-btn.btn-resume { background: rgba(0, 255, 200, 0.14); color: #00ffc8; border-color: rgba(0, 255, 200, 0.4); }
        .icon-btn.btn-resume:hover { background: rgba(0, 255, 200, 0.26); color: #fff; }

        .btn-pause-all {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 6px 12px; font-size: 12px; font-weight: 600;
            border-radius: 8px;
            background: rgba(255, 159, 28, 0.12);
            border: 1px solid rgba(255, 159, 28, 0.35);
            color: #ffb84d;
            cursor: pointer;
        }

        .btn-pause-all:hover { background: rgba(255, 159, 28, 0.22); border-color: #ffb84d; }

        .btn-pause-all.all-paused {
            background: rgba(0, 255, 200, 0.13);
            border-color: rgba(0, 255, 200, 0.4);
            color: #00ffc8;
        }

        .mode-badge {
            display: inline-flex; align-items: center; gap: 4px;
            font-size: 9.5px; font-weight: 700;
            padding: 2px 7px;
            border-radius: 5px;
            letter-spacing: 0.3px;
            text-transform: uppercase;
        }

        .mode-badge.br {
            background: rgba(255, 159, 28, 0.15);
            color: #ffb84d;
            border: 1px solid rgba(255, 159, 28, 0.4);
        }
        .mode-badge.lw {
            background: rgba(168, 85, 247, 0.15);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.4);
        }
        .mode-badge.auto {
            background: rgba(0, 255, 200, 0.12);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 255, 200, 0.35);
        }

        .console-panel { display: flex; flex-direction: column; height: 900px; }

        .console-tools {
            display: flex; align-items: center; justify-content: space-between;
            gap: 10px; margin-bottom: 12px; flex-wrap: wrap;
        }

        .console-filter-pills { display: flex; gap: 6px; }

        .console-pill {
            background: rgba(168, 85, 247, 0.06);
            border: 1px solid rgba(168, 85, 247, 0.2);
            color: var(--text-dim);
            padding: 4px 10px; border-radius: 6px;
            font-size: 11px; font-weight: 600;
            cursor: pointer;
        }

        .console-pill.active { background: rgba(0, 255, 200, 0.15); color: var(--accent-cyan); border-color: rgba(0, 255, 200, 0.35); }

        .toggle-btn {
            background: rgba(168, 85, 247, 0.06);
            border: 1px solid rgba(168, 85, 247, 0.2);
            color: var(--text-muted);
            padding: 4px 10px; border-radius: 6px;
            font-size: 11px; cursor: pointer;
            display: inline-flex; align-items: center; gap: 6px;
        }

        .toggle-btn.active { color: var(--accent-cyan); border-color: rgba(0, 255, 200, 0.38); }

        .console-stream {
            flex: 1;
            background: #06040e;
            border: 1px solid rgba(168, 85, 247, 0.12);
            border-radius: var(--radius-md);
            padding: 14px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            overflow-y: auto;
            display: flex; flex-direction: column; gap: 6px;
            position: relative;
        }

        .console-stream::-webkit-scrollbar { width: 6px; }
        .console-stream::-webkit-scrollbar-thumb { background: rgba(168, 85, 247, 0.3); border-radius: 3px; }

        .log-entry {
            line-height: 1.5;
            word-break: break-all;
            display: flex; align-items: flex-start; gap: 8px;
        }

        .log-ts { color: #4a4570; flex-shrink: 0; font-size: 11px; }
        .log-txt.info { color: #66d9ff; }
        .log-txt.success { color: #00ffc8; }
        .log-txt.warning { color: #ffb84d; }
        .log-txt.error { color: #ff5c8a; }

        .empty-state { text-align: center; padding: 60px 20px; color: var(--text-dim); }
        .empty-state i { font-size: 48px; margin-bottom: 14px; color: rgba(168, 85, 247, 0.15); }
        .empty-state p { font-size: 14px; color: var(--text-muted); margin-bottom: 18px; }

        .modal-backdrop {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(4, 2, 14, 0.88);
            backdrop-filter: blur(10px);
            display: none;
            align-items: center; justify-content: center;
            z-index: 100;
            padding: 20px;
        }

        .modal-backdrop.active { display: flex; }

        .modal-box {
            background: #0d0920;
            border: 1px solid var(--border-card);
            border-radius: var(--radius-lg);
            width: 100%;
            max-width: 520px;
            padding: 28px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8);
            animation: modal-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
            max-height: 90vh;
            overflow-y: auto;
        }

        .modal-box.wide { max-width: 900px; }

        @keyframes modal-pop {
            0% { transform: scale(0.92) translateY(10px); opacity: 0; }
            100% { transform: scale(1) translateY(0); opacity: 1; }
        }

        .modal-top {
            display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 22px;
        }

        .modal-top h3 { font-size: 19px; font-weight: 700; display: flex; align-items: center; gap: 10px; }

        .form-field { margin-bottom: 18px; }
        .form-field label { display: block; font-size: 12px; font-weight: 700; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; }

        .form-control {
            width: 100%;
            background: rgba(168, 85, 247, 0.06);
            border: 1px solid rgba(168, 85, 247, 0.25);
            border-radius: 12px;
            padding: 11px 15px;
            color: #fff; font-size: 14px;
            outline: none;
        }

        .form-control:focus {
            border-color: rgba(0, 255, 200, 0.55);
            background: rgba(0, 255, 200, 0.08);
            box-shadow: 0 0 12px rgba(0, 255, 200, 0.25);
        }

        .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

        .info-box {
            display: flex; gap: 10px;
            padding: 12px 14px;
            background: rgba(0, 179, 255, 0.08);
            border: 1px solid rgba(0, 179, 255, 0.25);
            border-radius: 10px;
            font-size: 12px; color: var(--text-muted);
            margin-bottom: 16px;
            line-height: 1.6;
        }

        .info-box i { color: #66d9ff; font-size: 14px; flex-shrink: 0; margin-top: 2px; }

        .botfiles-split {
            display: grid;
            grid-template-columns: 340px 1fr;
            gap: 14px;
            min-height: 480px;
        }

        .bot-files-list {
            max-height: 62vh; overflow-y: auto;
            border: 1px solid rgba(168, 85, 247, 0.15);
            border-radius: var(--radius-md);
            background: rgba(0, 0, 0, 0.35);
            padding: 10px;
        }

        .bot-file-row {
            display: flex; align-items: center; gap: 10px;
            padding: 12px 13px;
            background: rgba(12, 10, 28, 0.6);
            border: 1px solid rgba(168, 85, 247, 0.15);
            border-radius: 10px;
            margin-bottom: 8px;
            cursor: pointer;
        }

        .bot-file-row:hover {
            border-color: rgba(0, 255, 200, 0.4);
            transform: translateX(3px);
        }

        .bot-file-row.active {
            border-color: var(--accent-cyan);
            background: rgba(0, 255, 200, 0.06);
            box-shadow: 0 0 0 1px rgba(0, 255, 200, 0.3), 0 0 18px rgba(0, 255, 200, 0.18);
        }

        .bot-file-icon {
            width: 34px; height: 34px;
            display: flex; align-items: center; justify-content: center;
            background: rgba(0, 255, 200, 0.10);
            border-radius: 9px;
            color: var(--accent-cyan); font-size: 13px; flex-shrink: 0;
        }

        .bot-file-info { flex: 1; min-width: 0; }
        .bot-file-name {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px; font-weight: 700; color: #fff;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .bot-file-meta { font-size: 10px; color: var(--text-dim); margin-top: 2px; }

        .bot-viewer {
            background: rgba(0, 0, 0, 0.55);
            border: 1px solid rgba(168, 85, 247, 0.15);
            border-radius: var(--radius-md);
            padding: 14px 16px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 11.5px;
            line-height: 1.7;
            color: #cbd5e1;
            overflow-y: auto;
            max-height: 62vh;
            white-space: pre-wrap;
            word-break: break-word;
            position: relative;
        }

        .bot-viewer::-webkit-scrollbar { width: 6px; }
        .bot-viewer::-webkit-scrollbar-thumb { background: rgba(168, 85, 247, 0.3); border-radius: 3px; }

        .bot-viewer-head {
            display: flex; align-items: center; justify-content: space-between;
            gap: 10px; margin-bottom: 12px; padding-bottom: 10px;
            border-bottom: 1px solid rgba(168, 85, 247, 0.15);
            position: sticky; top: 0;
            background: rgba(0, 0, 0, 0.55);
            z-index: 2;
        }

        .bot-viewer-name {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px; font-weight: 700;
            color: #fff;
            display: flex; align-items: center; gap: 8px;
            overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap;
        }

        .bot-viewer-actions { display: flex; gap: 6px; flex-shrink: 0; }
        .bot-viewer-actions .icon-btn { width: 30px; height: 30px; font-size: 11px; }

        .jv-key { color: #7dd3fc; }
        .jv-str { color: #00ffc8; }
        .jv-num { color: #ffb84d; }
        .jv-bool { color: #c084fc; }
        .jv-null { color: #94a3b8; }

        .toast-container {
            position: fixed;
            top: 24px; right: 24px;
            z-index: 1000;
            display: flex; flex-direction: column; gap: 10px;
            pointer-events: none;
        }

        .toast {
            background: rgba(13, 9, 32, 0.94);
            border: 1px solid var(--border-card);
            border-radius: var(--radius-md);
            padding: 12px 18px;
            color: #fff;
            font-size: 13px; font-weight: 600;
            backdrop-filter: blur(12px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
            display: flex; align-items: center; gap: 10px;
            pointer-events: auto;
            animation: toast-in 0.3s ease-out;
            max-width: 380px;
        }

        @keyframes toast-in {
            0% { transform: translateX(50px); opacity: 0; }
            100% { transform: translateX(0); opacity: 1; }
        }

        .toast.success { border-color: rgba(0, 255, 200, 0.55); color: #00ffc8; }
        .toast.error { border-color: rgba(255, 46, 99, 0.55); color: var(--accent-red); }
        .toast.info { border-color: rgba(0, 179, 255, 0.55); color: #66d9ff; }
        .toast.warning { border-color: rgba(255, 159, 28, 0.55); color: #ffb84d; }

        .mobile-header { display: none; }
        .mobile-bottom-nav { display: none; }

        @media (max-width: 1200px) {
            .stats-hero { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .options-bar { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .workspace-grid { grid-template-columns: 1fr; }
            .console-panel { height: 520px; }
            .botfiles-split { grid-template-columns: 1fr; min-height: auto; }
        }

        @media (max-width: 860px) {
            .stats-hero { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .options-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .accounts-grid { grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); }
        }

        @media (max-width: 768px) {
            body { padding-bottom: 84px; }
            .app-shell { padding: 14px; }
            .desktop-header { display: none; }

            .mobile-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 16px;
                background: var(--bg-card);
                border: 1px solid var(--border-card);
                border-radius: var(--radius-md);
                backdrop-filter: blur(16px);
                margin-bottom: 14px;
                position: sticky; top: 10px;
                z-index: 50;
            }

            .mobile-brand { display: flex; align-items: center; gap: 10px; }
            .mobile-brand h2 {
                font-size: 16px; font-weight: 800;
                background: linear-gradient(90deg, #fff, var(--accent-cyan));
                -webkit-background-clip: text; background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .stats-hero { grid-template-columns: 1fr 1fr; gap: 10px; }
            .stat-card { padding: 12px; min-height: 95px; }
            .stat-card .stat-data h2 { font-size: 18px; }
            .stat-card .stat-data p { font-size: 9.5px; }
            .stat-card .stat-icon-wrap { width: 32px; height: 32px; font-size: 13px; }

            .options-bar { grid-template-columns: 1fr; gap: 10px; }
            .option-card {
                min-height: 0;
                flex-direction: row;
                align-items: center;
                gap: 14px;
                padding: 14px;
            }
            .option-card .opt-icon { width: 40px; height: 40px; font-size: 17px; }
            .option-card .opt-num { top: 50%; right: 14px; transform: translateY(-50%); }
            .option-card .opt-cta { display: none; }
            .option-card h4 { font-size: 13px; }
            .option-card p { font-size: 10.5px; }

            .mobile-tab-view { display: none; }
            .mobile-tab-view.active-tab { display: block; }

            .panel-box { padding: 16px; }
            .console-panel { height: calc(100vh - 220px); }

            .accounts-grid { grid-template-columns: 1fr; max-height: none; }

            .modal-backdrop { align-items: flex-end; padding: 0; }
            .modal-box {
                max-width: 100%;
                border-radius: 24px 24px 0 0;
                padding: 24px 20px 36px 20px;
                animation: sheet-up 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
            }

            @keyframes sheet-up {
                0% { transform: translateY(100%); }
                100% { transform: translateY(0); }
            }

            .mobile-bottom-nav {
                position: fixed;
                bottom: 0; left: 0; right: 0;
                height: 68px;
                background: rgba(8, 6, 18, 0.96);
                border-top: 1px solid var(--border-card);
                backdrop-filter: blur(20px);
                display: flex; align-items: center; justify-content: space-around;
                z-index: 90;
                padding: 0 10px;
            }

            .mobile-nav-item {
                display: flex; flex-direction: column; align-items: center;
                gap: 4px;
                color: var(--text-dim);
                font-size: 10px; font-weight: 600;
                background: none; border: none; cursor: pointer;
                padding: 8px 12px;
                border-radius: 12px;
            }

            .mobile-nav-item i { font-size: 18px; }

            .mobile-nav-item.active {
                color: var(--accent-cyan);
                background: rgba(0, 255, 200, 0.12);
            }

            .toast-container { top: 12px; left: 14px; right: 14px; }

            .form-row { grid-template-columns: 1fr; }
            .exp-strip { grid-template-columns: 1fr 1fr; }
            .exp-strip .exp-col:last-child { grid-column: span 2; }
        }
    </style>
</head>
<body>

<div class="toast-container" id="toast-container"></div>

<div class="app-shell">
    <header class="desktop-header">
        <div class="brand">
            <div class="brand-logo"><i class="fa-solid fa-bolt"></i></div>
            <div class="brand-title">
                <h1>MAHIR <span style="font-weight:400; color:var(--text-muted); font-size:14px;">v3.0</span></h1>
                <div class="brand-sub">
                    <span class="badge-live"><span class="radar-dot"></span> System Live</span>
                    <span class="badge-mode" id="brand-active-mode">MODE: IDLE</span>
                    <span id="brand-uptime" style="font-family:'JetBrains Mono',monospace; color:var(--accent-cyan); font-weight:700;">00:00:00</span>
                </div>
            </div>
        </div>
        <div class="header-controls">
            <button class="btn btn-secondary" onclick="manualRefresh()"><i class="fa-solid fa-rotate"></i> Refresh</button>
            <button class="btn btn-secondary" onclick="openBotFiles()"><i class="fa-solid fa-folder-open"></i> Bot Files</button>
            <button class="btn btn-secondary" onclick="openManagePanel()"><i class="fa-solid fa-users-gear"></i> Manage</button>
        </div>
    </header>

    <div class="mobile-header">
        <div class="mobile-brand">
            <div class="brand-logo" style="width:36px; height:36px; font-size:16px;"><i class="fa-solid fa-bolt"></i></div>
            <div>
                <h2>MAHIR v3.0</h2>
                <span class="badge-live" style="font-size:9px; padding:1px 6px;"><span class="radar-dot" style="width:6px; height:6px;"></span> Live</span>
            </div>
        </div>
        <div style="display:flex; gap:6px;">
            <button class="icon-btn" onclick="openBotFiles()"><i class="fa-solid fa-folder-open"></i></button>
            <button class="icon-btn" onclick="openManagePanel()"><i class="fa-solid fa-users-gear"></i></button>
            <button class="icon-btn" onclick="manualRefresh()"><i class="fa-solid fa-rotate"></i></button>
        </div>
    </div>

    <section class="stats-hero">
        <div class="stat-card cyan">
            <div class="stat-icon-wrap cyan"><i class="fa-solid fa-users"></i></div>
            <div class="stat-data">
                <p>Accounts</p>
                <h2 id="stat-accs">0</h2>
            </div>
        </div>
        <div class="stat-card green">
            <div class="stat-icon-wrap green"><i class="fa-solid fa-rocket"></i></div>
            <div class="stat-data">
                <p>Matches Started</p>
                <h2 id="stat-started">0</h2>
            </div>
        </div>
        <div class="stat-card purple">
            <div class="stat-icon-wrap purple"><i class="fa-solid fa-flag-checkered"></i></div>
            <div class="stat-data">
                <p>Matches Done</p>
                <h2 id="stat-done">0</h2>
            </div>
        </div>
        <div class="stat-card amber">
            <div class="stat-icon-wrap amber"><i class="fa-solid fa-arrow-trend-up"></i></div>
            <div class="stat-data">
                <p>Total EXP</p>
                <h2 id="stat-exp">+0</h2>
            </div>
        </div>
        <div class="stat-card pink">
            <div class="stat-icon-wrap pink"><i class="fa-solid fa-file-code"></i></div>
            <div class="stat-data">
                <p>Bot Files</p>
                <h2 id="stat-files">0</h2>
            </div>
        </div>
    </section>

    <section class="options-bar">
        <div class="option-card o1" onclick="openOption1Modal()">
            <div class="opt-num">01</div>
            <div class="opt-icon"><i class="fa-solid fa-user"></i></div>
            <h4>Solo BR</h4>
            <p>Add single account manually, plays Battle Royale solo.</p>
            <div class="opt-cta">Start <i class="fa-solid fa-arrow-right"></i></div>
        </div>
        <div class="option-card o2" onclick="openTeamModal()">
            <div class="opt-num">02</div>
            <div class="opt-icon"><i class="fa-solid fa-users"></i></div>
            <h4>Team Mode 4-Bot</h4>
            <p>Auto-create 4 accounts, join clan, play as full team.</p>
            <div class="opt-cta">Start <i class="fa-solid fa-arrow-right"></i></div>
        </div>
        <div class="option-card o3" onclick="openAutoModal()">
            <div class="opt-num">03</div>
            <div class="opt-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
            <h4>Auto + Bio + AUTO</h4>
            <p>BR until Level 3, then auto-switch to Lone Wolf.</p>
            <div class="opt-cta">Start <i class="fa-solid fa-arrow-right"></i></div>
        </div>
        <div class="option-card o4" onclick="openGuildModal()">
            <div class="opt-num">04</div>
            <div class="opt-icon"><i class="fa-solid fa-building-flag"></i></div>
            <h4>Auto + Guild + BR</h4>
            <p>Auto-create, send guild request, play Battle Royale.</p>
            <div class="opt-cta">Start <i class="fa-solid fa-arrow-right"></i></div>
        </div>
        <div class="option-card o5" onclick="openManagePanel()">
            <div class="opt-num">05</div>
            <div class="opt-icon"><i class="fa-solid fa-users-gear"></i></div>
            <h4>Account Management</h4>
            <p>View, copy, delete accounts and manage JSON files.</p>
            <div class="opt-cta">Open <i class="fa-solid fa-arrow-right"></i></div>
        </div>
    </section>

    <div class="workspace-grid">
        <div class="panel-box mobile-tab-view active-tab" id="tab-accounts">
            <div class="panel-header">
                <div class="panel-title">
                    <i class="fa-solid fa-user-astronaut" style="color:var(--accent-cyan); font-size:20px;"></i>
                    <h3>Accounts & EXP Tracker</h3>
                    <span class="counter-pill" id="badge-acc-count">0 Loaded</span>
                </div>
                <div>
                    <button class="btn-pause-all" id="btn-global-pause" onclick="togglePauseAll()">
                        <i class="fa-solid fa-pause"></i> <span>Pause All</span>
                    </button>
                </div>
            </div>

            <div class="filter-row">
                <div class="search-box">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <input type="text" id="account-search-input" placeholder="Search by Nickname or UID..." oninput="filterAccounts()">
                </div>
                <div class="filter-tabs">
                    <button class="filter-btn active" data-filter="all" onclick="setFilter('all', this)">All</button>
                    <button class="filter-btn" data-filter="in_match" onclick="setFilter('in_match', this)">In Match</button>
                    <button class="filter-btn" data-filter="online" onclick="setFilter('online', this)">Online</button>
                    <button class="filter-btn" data-filter="paused" onclick="setFilter('paused', this)">Paused</button>
                </div>
            </div>

            <div class="accounts-grid" id="accounts-container">
                <div class="empty-state" style="grid-column:1/-1">
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                    <p>Connecting to Bot Core...</p>
                </div>
            </div>
        </div>

        <div class="panel-box console-panel mobile-tab-view" id="tab-console">
            <div class="panel-header">
                <div class="panel-title">
                    <i class="fa-solid fa-terminal" style="color:var(--accent-cyan); font-size:18px;"></i>
                    <h3>Live Console</h3>
                </div>
                <div>
                    <button class="icon-btn" onclick="clearLogs()" title="Clear"><i class="fa-solid fa-trash-can"></i></button>
                </div>
            </div>

            <div class="console-tools">
                <div class="console-filter-pills">
                    <button class="console-pill active" onclick="setLogFilter('all', this)">All</button>
                    <button class="console-pill" onclick="setLogFilter('match', this)">Matches</button>
                    <button class="console-pill" onclick="setLogFilter('success', this)">EXP</button>
                    <button class="console-pill" onclick="setLogFilter('error', this)">Errors</button>
                </div>
                <button class="toggle-btn active" id="btn-autoscroll" onclick="toggleAutoScroll()">
                    <i class="fa-solid fa-arrows-down-to-line"></i> Auto
                </button>
            </div>

            <div class="console-stream" id="console-stream"></div>
        </div>
    </div>
</div>

<nav class="mobile-bottom-nav">
    <button class="mobile-nav-item active" onclick="switchMobileTab('accounts', this)">
        <i class="fa-solid fa-user-group"></i><span>Accounts</span>
    </button>
    <button class="mobile-nav-item" onclick="switchMobileTab('console', this)">
        <i class="fa-solid fa-terminal"></i><span>Console</span>
    </button>
    <button class="mobile-nav-item" onclick="openManagePanel()">
        <i class="fa-solid fa-users-gear"></i><span>Manage</span>
    </button>
    <button class="mobile-nav-item" onclick="openBotFiles()">
        <i class="fa-solid fa-folder-open"></i><span>Files</span>
    </button>
</nav>

<div class="modal-backdrop" id="modal-add">
    <div class="modal-box">
        <div class="modal-top">
            <h3><i class="fa-solid fa-user-plus" style="color:var(--accent-cyan)"></i> Add Single Account</h3>
            <button class="icon-btn" onclick="closeModal('modal-add')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="info-box">
            <i class="fa-solid fa-info-circle"></i>
            <div>Add a guest account to run Solo Battle Royale. Play mode can be changed later from account card.</div>
        </div>
        <form onsubmit="submitAddAccount(event)">
            <div class="form-field">
                <label>Login Type</label>
                <select class="form-control" id="acc-type" onchange="toggleAddType()">
                    <option value="guest">Guest Account (UID + Password)</option>
                    <option value="token">Access Token</option>
                </select>
            </div>
            <div id="guest-inputs">
                <div class="form-field">
                    <label>Guest UID</label>
                    <input type="text" class="form-control" id="acc-uid" placeholder="e.g. 7872038363" autocomplete="off">
                </div>
                <div class="form-field">
                    <label>Guest Password / Key</label>
                    <input type="text" class="form-control" id="acc-password" placeholder="e.g. 381002140664..." autocomplete="off">
                </div>
            </div>
            <div id="token-inputs" style="display:none;">
                <div class="form-field">
                    <label>Access Token</label>
                    <textarea class="form-control" id="acc-token" rows="3" placeholder="Paste token..." style="font-family:'JetBrains Mono',monospace;font-size:12px;"></textarea>
                </div>
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:22px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal('modal-add')">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-rocket"></i> Save & Start</button>
            </div>
        </form>
    </div>
</div>

<div class="modal-backdrop" id="modal-team">
    <div class="modal-box">
        <div class="modal-top">
            <h3><i class="fa-solid fa-users" style="color:#c084fc"></i> Team Mode 4-Bot</h3>
            <button class="icon-btn" onclick="closeModal('modal-team')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="info-box">
            <i class="fa-solid fa-users"></i>
            <div>Creates 4 new accounts, joins them all to your clan, and runs as a coordinated team playing BR matches.</div>
        </div>
        <form onsubmit="submitTeam(event)">
            <div class="form-row">
                <div class="form-field">
                    <label>Region</label>
                    <select class="form-control" id="team-region">
                        <option value="BD">BD — Bangladesh</option>
                        <option value="IND">IND — India</option>
                        <option value="ID">ID — Indonesia</option>
                        <option value="ME">ME — Middle East</option>
                        <option value="PK">PK — Pakistan</option>
                        <option value="VN">VN — Vietnam</option>
                        <option value="TH">TH — Thailand</option>
                        <option value="TW">TW — Taiwan</option>
                        <option value="RU">RU — Russia</option>
                        <option value="SAC">SAC — South America</option>
                        <option value="BR">BR — Brazil</option>
                        <option value="NA">NA — North America</option>
                    </select>
                </div>
                <div class="form-field">
                    <label>Clan ID</label>
                    <input type="text" class="form-control" id="team-clan" value="3087207343">
                </div>
            </div>
            <div class="form-row">
                <div class="form-field">
                    <label>Bot Count</label>
                    <select class="form-control" id="team-count">
                        <option value="4" selected>4 bots (full team)</option>
                        <option value="3">3 bots</option>
                        <option value="2">2 bots</option>
                    </select>
                </div>
                <div class="form-field">
                    <label>Password Prefix</label>
                    <input type="text" class="form-control" id="team-pass" value="MAHIR" readonly style="opacity:.7">
                </div>
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:22px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal('modal-team')">Cancel</button>
                <button type="submit" class="btn btn-primary" id="btn-team-submit"><i class="fa-solid fa-bolt"></i> Create & Start</button>
            </div>
        </form>
    </div>
</div>

<div class="modal-backdrop" id="modal-auto">
    <div class="modal-box">
        <div class="modal-top">
            <h3><i class="fa-solid fa-wand-magic-sparkles" style="color:var(--accent-cyan)"></i> Auto + Bio + AUTO Gameplay</h3>
            <button class="icon-btn" onclick="closeModal('modal-auto')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="info-box">
            <i class="fa-solid fa-wand-magic-sparkles"></i>
            <div>Auto-creates accounts, sets Bio, plays <b>BR until Level 3</b>, then <b>auto-switches to Lone Wolf</b>. Best for fast leveling.</div>
        </div>
        <form onsubmit="submitAuto(event)">
            <div class="form-row">
                <div class="form-field">
                    <label>Region</label>
                    <select class="form-control" id="auto-region">
                        <option value="BD">BD — Bangladesh</option>
                        <option value="IND">IND — India</option>
                        <option value="ID">ID — Indonesia</option>
                        <option value="ME">ME — Middle East</option>
                        <option value="PK">PK — Pakistan</option>
                        <option value="VN">VN — Vietnam</option>
                        <option value="TH">TH — Thailand</option>
                        <option value="TW">TW — Taiwan</option>
                    </select>
                </div>
                <div class="form-field">
                    <label>Bot Count</label>
                    <select class="form-control" id="auto-count">
                        <option value="1">1 bot</option>
                        <option value="2">2 bots</option>
                        <option value="3">3 bots</option>
                        <option value="4" selected>4 bots</option>
                        <option value="6">6 bots</option>
                        <option value="8">8 bots</option>
                        <option value="10">10 bots</option>
                    </select>
                </div>
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:22px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal('modal-auto')">Cancel</button>
                <button type="submit" class="btn btn-success" id="btn-auto-submit"><i class="fa-solid fa-wand-magic-sparkles"></i> Create & Auto-Play</button>
            </div>
        </form>
    </div>
</div>

<div class="modal-backdrop" id="modal-guild">
    <div class="modal-box">
        <div class="modal-top">
            <h3><i class="fa-solid fa-building-flag" style="color:var(--accent-amber)"></i> Auto + Bio + Guild Request + BR</h3>
            <button class="icon-btn" onclick="closeModal('modal-guild')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="info-box">
            <i class="fa-solid fa-building-flag"></i>
            <div>Auto-creates accounts, sets Bio, sends <b>Guild Join Request</b> to your clan, then plays <b>Battle Royale</b> continuously.</div>
        </div>
        <form onsubmit="submitGuild(event)">
            <div class="form-row">
                <div class="form-field">
                    <label>Region</label>
                    <select class="form-control" id="guild-region">
                        <option value="BD">BD — Bangladesh</option>
                        <option value="IND">IND — India</option>
                        <option value="ID">ID — Indonesia</option>
                        <option value="ME">ME — Middle East</option>
                        <option value="PK">PK — Pakistan</option>
                        <option value="VN">VN — Vietnam</option>
                        <option value="TH">TH — Thailand</option>
                        <option value="TW">TW — Taiwan</option>
                    </select>
                </div>
                <div class="form-field">
                    <label>Clan ID</label>
                    <input type="text" class="form-control" id="guild-clan" value="3087207343">
                </div>
            </div>
            <div class="form-field">
                <label>Bot Count</label>
                <select class="form-control" id="guild-count">
                    <option value="1">1 bot</option>
                    <option value="2">2 bots</option>
                    <option value="3">3 bots</option>
                    <option value="4" selected>4 bots</option>
                    <option value="6">6 bots</option>
                    <option value="8">8 bots</option>
                    <option value="10">10 bots</option>
                </select>
            </div>
            <div style="display:flex; gap:10px; justify-content:flex-end; margin-top:22px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal('modal-guild')">Cancel</button>
                <button type="submit" class="btn btn-warn" id="btn-guild-submit"><i class="fa-solid fa-building-flag"></i> Create & Guild-BR</button>
            </div>
        </form>
    </div>
</div>

<div class="modal-backdrop" id="modal-botfiles">
    <div class="modal-box wide">
        <div class="modal-top">
            <h3><i class="fa-solid fa-folder-open" style="color:var(--accent-cyan)"></i> Bot Account Files</h3>
            <button class="icon-btn" onclick="closeModal('modal-botfiles')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div style="display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap;">
            <button class="btn btn-primary" onclick="downloadAllBotFiles()">
                <i class="fa-solid fa-file-zipper"></i> Download All (ZIP)
            </button>
            <button class="btn btn-secondary" onclick="loadBotFiles()">
                <i class="fa-solid fa-rotate"></i> Refresh
            </button>
            <input id="botfiles-search" class="form-control" style="flex:1;min-width:160px" placeholder="Search nickname / UID..." oninput="filterBotFiles()">
        </div>

        <div class="botfiles-split">
            <div class="bot-files-list" id="bot-files-list">
                <div class="empty-state" style="padding:30px 20px">
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                    <p>Loading files...</p>
                </div>
            </div>
            <div class="bot-viewer" id="bot-viewer">
                <div class="empty-state" style="padding:40px 20px">
                    <i class="fa-solid fa-file-code"></i>
                    <p>Select a file to view JSON</p>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="modal-backdrop" id="modal-manage">
    <div class="modal-box wide">
        <div class="modal-top">
            <h3><i class="fa-solid fa-users-gear" style="color:var(--accent-pink)"></i> Account Management</h3>
            <button class="icon-btn" onclick="closeModal('modal-manage')"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="info-box">
            <i class="fa-solid fa-shield-halved"></i>
            <div>Full account control: view UID / Password / Nickname / Status / JSON file. Click any row to see full details.</div>
        </div>

        <div style="display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap;">
            <button class="btn btn-secondary" onclick="loadManageAccounts()">
                <i class="fa-solid fa-rotate"></i> Refresh
            </button>
            <input id="manage-search" class="form-control" style="flex:1;min-width:160px" placeholder="Search nickname / UID..." oninput="filterManageAccounts()">
        </div>

        <div class="botfiles-split">
            <div class="bot-files-list" id="manage-list">
                <div class="empty-state" style="padding:30px 20px">
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                    <p>Loading...</p>
                </div>
            </div>
            <div class="bot-viewer" id="manage-viewer">
                <div class="empty-state" style="padding:40px 20px">
                    <i class="fa-solid fa-user"></i>
                    <p>Select account to view details</p>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    let cachedAccounts = [];
    let cachedLogs = [];
    let cachedBotFiles = [];
    let cachedManageAccounts = [];
    let activeBotFile = null;
    let activeManageUid = null;
    let autoScrollEnabled = true;
    let activeFilter = 'all';
    let activeLogFilter = 'all';
    let localClientTime = Date.now();

    const uptimeBaselines = {};

    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icons = {
            success: 'fa-circle-check',
            error: 'fa-triangle-exclamation',
            warning: 'fa-pause',
            info: 'fa-circle-info'
        };
        toast.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i> <span>${escapeHtml(message)}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3400);
    }

    function openModal(id) { document.getElementById(id).classList.add('active'); }
    function closeModal(id) { document.getElementById(id).classList.remove('active'); }

    document.querySelectorAll('.modal-backdrop').forEach(m => {
        m.addEventListener('click', e => { if (e.target === m) m.classList.remove('active'); });
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-backdrop.active').forEach(m => m.classList.remove('active'));
        }
    });

    function openOption1Modal() { openModal('modal-add'); }
    function toggleAddType() {
        const t = document.getElementById('acc-type').value;
        document.getElementById('guest-inputs').style.display = t === 'guest' ? 'block' : 'none';
        document.getElementById('token-inputs').style.display = t === 'token' ? 'block' : 'none';
    }

    async function submitAddAccount(e) {
        e.preventDefault();
        const type = document.getElementById('acc-type').value;
        let payload = {};
        if (type === 'guest') {
            const uid = document.getElementById('acc-uid').value.trim();
            const password = document.getElementById('acc-password').value.trim();
            if (!uid || !password) return showToast('Please enter both UID and Password', 'error');
            payload = { uid, password };
        } else {
            const token = document.getElementById('acc-token').value.trim();
            if (!token) return showToast('Please paste a valid access token', 'error');
            payload = { token };
        }
        try {
            const r = await fetch('/api/account/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const d = await r.json();
            if (d.status === 'ok') {
                closeModal('modal-add');
                document.getElementById('acc-uid').value = '';
                document.getElementById('acc-password').value = '';
                document.getElementById('acc-token').value = '';
                showToast('Account added', 'success');
                fetchStats();
            } else {
                showToast('Failed: ' + (d.error || 'Unknown'), 'error');
            }
        } catch (err) { showToast('Network error', 'error'); }
    }

    function openTeamModal() {
        const btn = document.getElementById('btn-team-submit');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Create & Start';
        openModal('modal-team');
    }

    async function submitTeam(e) {
        e.preventDefault();
        const region = document.getElementById('team-region').value;
        const clan_id = document.getElementById('team-clan').value.trim();
        const count = parseInt(document.getElementById('team-count').value, 10);
        const password = document.getElementById('team-pass').value.trim() || 'MAHIR';
        if (!clan_id) return showToast('Clan ID required', 'error');

        const btn = document.getElementById('btn-team-submit');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Starting...';

        try {
            const r = await fetch('/api/create_team', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ region, clan_id, count, password })
            });
            const d = await r.json();
            if (d.ok) {
                closeModal('modal-team');
                showToast(`Creating ${count} TEAM bots...`, 'success');
                setTimeout(fetchStats, 3000);
                setTimeout(fetchStats, 8000);
                setTimeout(fetchStats, 15000);
            } else {
                showToast(d.error || 'Failed', 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Create & Start';
            }
        } catch (err) {
            showToast('Network error', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Create & Start';
        }
    }

    function openAutoModal() {
        const btn = document.getElementById('btn-auto-submit');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Create & Auto-Play';
        openModal('modal-auto');
    }

    async function submitAuto(e) {
        e.preventDefault();
        const region = document.getElementById('auto-region').value;
        const count = parseInt(document.getElementById('auto-count').value, 10);

        const btn = document.getElementById('btn-auto-submit');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Starting...';

        try {
            const r = await fetch('/api/create_auto', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ region, count })
            });
            const d = await r.json();
            if (d.ok) {
                closeModal('modal-auto');
                showToast(`Creating ${count} AUTO bots (BR→LW)`, 'success');
                setTimeout(fetchStats, 3000);
                setTimeout(fetchStats, 8000);
                setTimeout(fetchStats, 15000);
            } else {
                showToast(d.error || 'Failed', 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Create & Auto-Play';
            }
        } catch (err) {
            showToast('Network error', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Create & Auto-Play';
        }
    }

    function openGuildModal() {
        const btn = document.getElementById('btn-guild-submit');
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-building-flag"></i> Create & Guild-BR';
        openModal('modal-guild');
    }

    async function submitGuild(e) {
        e.preventDefault();
        const region = document.getElementById('guild-region').value;
        const clan_id = document.getElementById('guild-clan').value.trim();
        const count = parseInt(document.getElementById('guild-count').value, 10);
        if (!clan_id) return showToast('Clan ID required', 'error');

        const btn = document.getElementById('btn-guild-submit');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Starting...';

        try {
            const r = await fetch('/api/create_guild', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ region, clan_id, count })
            });
            const d = await r.json();
            if (d.ok) {
                closeModal('modal-guild');
                showToast(`Creating ${count} GUILD bots + BR`, 'success');
                setTimeout(fetchStats, 3000);
                setTimeout(fetchStats, 8000);
                setTimeout(fetchStats, 15000);
            } else {
                showToast(d.error || 'Failed', 'error');
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-building-flag"></i> Create & Guild-BR';
            }
        } catch (err) {
            showToast('Network error', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-building-flag"></i> Create & Guild-BR';
        }
    }

    function openBotFiles() {
        openModal('modal-botfiles');
        loadBotFiles();
    }

    async function loadBotFiles() {
        const wrap = document.getElementById('bot-files-list');
        wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-circle-notch fa-spin"></i><p>Loading...</p></div>';
        try {
            const r = await fetch('/api/bot_files');
            const d = await r.json();
            cachedBotFiles = d.files || [];
            renderBotFiles(cachedBotFiles);
        } catch (err) {
            wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load</p></div>';
        }
    }

    function renderBotFiles(files) {
        const wrap = document.getElementById('bot-files-list');
        if (!files.length) {
            wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-folder-open"></i><p>No bot files yet</p></div>';
            return;
        }
        wrap.innerHTML = files.map(f => {
            const active = activeBotFile === f.filename ? 'active' : '';
            return `
                <div class="bot-file-row ${active}" data-file="${escapeAttr(f.filename)}" onclick="viewBotFile('${escapeAttr(f.filename)}')">
                    <div class="bot-file-icon"><i class="fa-solid fa-file-code"></i></div>
                    <div class="bot-file-info">
                        <div class="bot-file-name">${escapeHtml(f.filename)}</div>
                        <div class="bot-file-meta">${escapeHtml(f.nickname || '—')} • UID ${escapeHtml(f.uid)}</div>
                    </div>
                    <button class="icon-btn" onclick="event.stopPropagation(); downloadBotFile('${escapeAttr(f.filename)}')" title="Download">
                        <i class="fa-solid fa-download"></i>
                    </button>
                    <button class="icon-btn danger" onclick="event.stopPropagation(); deleteBotFile('${escapeAttr(f.filename)}')" title="Delete">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');
    }

    function filterBotFiles() {
        const q = (document.getElementById('botfiles-search').value || '').toLowerCase().trim();
        if (!q) { renderBotFiles(cachedBotFiles); return; }
        const filtered = cachedBotFiles.filter(f =>
            (f.filename || '').toLowerCase().includes(q) ||
            (f.nickname || '').toLowerCase().includes(q) ||
            (f.uid || '').toLowerCase().includes(q)
        );
        renderBotFiles(filtered);
    }

    async function viewBotFile(filename) {
        activeBotFile = filename;
        document.querySelectorAll('.bot-file-row').forEach(r => {
            r.classList.toggle('active', r.dataset.file === filename);
        });
        const viewer = document.getElementById('bot-viewer');
        viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-circle-notch fa-spin"></i><p>Loading...</p></div>';

        try {
            const r = await fetch('/api/bot_files/view?file=' + encodeURIComponent(filename));
            const d = await r.json();
            if (d.status !== 'ok' || !d.data) {
                viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load</p></div>';
                return;
            }
            const json = JSON.stringify(d.data, null, 2);
            const colored = syntaxHighlightJson(json);

            viewer.innerHTML = `
                <div class="bot-viewer-head">
                    <span class="bot-viewer-name">
                        <i class="fa-solid fa-file-code" style="color:var(--accent-cyan)"></i>${escapeHtml(filename)}
                    </span>
                    <div class="bot-viewer-actions">
                        <button class="icon-btn" onclick="copyBotFileContent('${escapeAttr(filename)}')" title="Copy JSON">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                        <button class="icon-btn" onclick="downloadBotFile('${escapeAttr(filename)}')" title="Download">
                            <i class="fa-solid fa-download"></i>
                        </button>
                        <button class="icon-btn danger" onclick="deleteBotFile('${escapeAttr(filename)}')" title="Delete">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div>${colored}</div>
            `;
        } catch (err) {
            viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Network error</p></div>';
        }
    }

    function syntaxHighlightJson(json) {
        let s = escapeHtml(json);
        s = s.replace(/&quot;([^&]*?)&quot;(\s*:)/g, '<span class="jv-key">&quot;$1&quot;</span>$2');
        s = s.replace(/:(\s*)&quot;([^&]*?)&quot;/g, ':$1<span class="jv-str">&quot;$2&quot;</span>');
        s = s.replace(/(:\s*)(-?\d+\.?\d*)/g, '$1<span class="jv-num">$2</span>');
        s = s.replace(/\b(true|false)\b/g, '<span class="jv-bool">$1</span>');
        s = s.replace(/\bnull\b/g, '<span class="jv-null">null</span>');
        return s;
    }

    async function copyBotFileContent(filename) {
        try {
            const r = await fetch('/api/bot_files/view?file=' + encodeURIComponent(filename));
            const d = await r.json();
            if (d.status !== 'ok' || !d.data) return showToast('Failed to load', 'error');
            const json = JSON.stringify(d.data, null, 2);
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(json);
                showToast('JSON copied', 'success');
            } else {
                showToast('Clipboard not supported', 'error');
            }
        } catch (e) { showToast('Copy failed', 'error'); }
    }

    function downloadBotFile(name) {
        window.location = '/api/bot_files/download?file=' + encodeURIComponent(name);
    }
    function downloadAllBotFiles() {
        window.location = '/api/bot_files/download_all';
    }
    async function deleteBotFile(name) {
        if (!confirm('Delete ' + name + '?')) return;
        try {
            const r = await fetch('/api/bot_files/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file: name })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast('Deleted', 'success');
                if (activeBotFile === name) {
                    activeBotFile = null;
                    document.getElementById('bot-viewer').innerHTML =
                        '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-file-code"></i><p>Select a file to view JSON</p></div>';
                }
                loadBotFiles();
            } else showToast('Delete failed', 'error');
        } catch (e) { showToast('Network error', 'error'); }
    }

    function openManagePanel() {
        openModal('modal-manage');
        loadManageAccounts();
    }

    async function loadManageAccounts() {
        const wrap = document.getElementById('manage-list');
        wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-circle-notch fa-spin"></i><p>Loading...</p></div>';
        try {
            const r = await fetch('/api/accounts/manage_list');
            const d = await r.json();
            cachedManageAccounts = d.accounts || [];
            renderManageAccounts(cachedManageAccounts);
        } catch (err) {
            wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load</p></div>';
        }
    }

    function renderManageAccounts(accs) {
        const wrap = document.getElementById('manage-list');
        if (!accs.length) {
            wrap.innerHTML = '<div class="empty-state" style="padding:30px 20px"><i class="fa-solid fa-users"></i><p>No accounts yet</p></div>';
            return;
        }
        wrap.innerHTML = accs.map(a => {
            const active = activeManageUid === a.uid ? 'active' : '';
            return `
                <div class="bot-file-row ${active}" data-uid="${escapeAttr(a.uid)}" onclick="viewManageAccount('${escapeAttr(a.uid)}')">
                    <div class="bot-file-icon" style="background:rgba(236,72,153,0.15);color:#f9a8d4;">
                        <i class="fa-solid fa-user"></i>
                    </div>
                    <div class="bot-file-info">
                        <div class="bot-file-name">${escapeHtml(a.nickname || 'Unknown')} <span style="color:var(--text-dim);font-weight:400;">[L${a.level}]</span></div>
                        <div class="bot-file-meta">
                            UID: ${escapeHtml(a.uid)} • ${escapeHtml(a.region || 'BD')} • 
                            <span style="color:${a.is_paused ? '#ffb84d' : '#00ffc8'}">${a.is_paused ? 'PAUSED' : (a.status || 'ONLINE')}</span>
                        </div>
                    </div>
                    <button class="icon-btn" onclick="event.stopPropagation(); copyUid('${escapeAttr(a.uid)}')" title="Copy UID">
                        <i class="fa-regular fa-copy"></i>
                    </button>
                    <button class="icon-btn danger" onclick="event.stopPropagation(); deleteManagedAccount('${escapeAttr(a.uid)}', '${escapeAttr(a.auth_uid || '')}')" title="Delete">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                </div>
            `;
        }).join('');
    }

    function filterManageAccounts() {
        const q = (document.getElementById('manage-search').value || '').toLowerCase().trim();
        if (!q) { renderManageAccounts(cachedManageAccounts); return; }
        const filtered = cachedManageAccounts.filter(a =>
            (a.uid || '').toLowerCase().includes(q) ||
            (a.nickname || '').toLowerCase().includes(q)
        );
        renderManageAccounts(filtered);
    }

    let _showPwd = {};
    async function viewManageAccount(uid) {
        activeManageUid = uid;
        document.querySelectorAll('#manage-list .bot-file-row').forEach(r => {
            r.classList.toggle('active', r.dataset.uid === uid);
        });
        const viewer = document.getElementById('manage-viewer');
        viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-circle-notch fa-spin"></i><p>Loading...</p></div>';

        try {
            const r = await fetch('/api/accounts/manage_view?uid=' + encodeURIComponent(uid));
            const d = await r.json();
            if (d.status !== 'ok' || !d.data) {
                viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Failed to load</p></div>';
                return;
            }
            const data = d.data;
            const json_data = data.json_data || {};
            const state = data.state || {};

            const nickname = json_data.nickname || state.nickname || '—';
            const account_id = json_data.account_id || state.uid || uid;
            const auth_uid = json_data.uid || state.auth_uid || uid;
            const password = json_data.password || '—';
            const status = state.is_paused ? 'PAUSED' : (state.status || json_data.status || 'IDLE');
            const json_file = data.json_file || '—';
            const level = json_data.level || state.level || 1;
            const region = json_data.region || state.region || 'BD';
            const exp = json_data.exp || state.current_exp || 0;
            const mode = json_data.mode || state.selected_mode || 'AUTO';
            const matches = state.matches_played || 0;

            const pwdShown = _showPwd[uid] ? password : '••••••••';
            const eyeIcon = _showPwd[uid] ? 'fa-eye-slash' : 'fa-eye';

            viewer.innerHTML = `
                <div class="bot-viewer-head">
                    <span class="bot-viewer-name">
                        <i class="fa-solid fa-user" style="color:var(--accent-pink)"></i> ${escapeHtml(nickname)}
                    </span>
                    <div class="bot-viewer-actions">
                        <button class="icon-btn" onclick="copyJsonData('${escapeAttr(uid)}')" title="Copy JSON">
                            <i class="fa-solid fa-code"></i>
                        </button>
                    </div>
                </div>

                <div style="display:flex;flex-direction:column;gap:12px;">
                    <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                        <span style="font-size:11px;font-weight:700;color:var(--text-dim);width:90px;text-transform:uppercase;">Account ID</span>
                        <span style="flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;color:#fff;">${escapeHtml(String(account_id))}</span>
                        <button class="icon-btn" onclick="copyUid('${escapeAttr(String(account_id))}')" title="Copy ID">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </div>

                    <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                        <span style="font-size:11px;font-weight:700;color:var(--text-dim);width:90px;text-transform:uppercase;">Auth UID</span>
                        <span style="flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;color:#fff;">${escapeHtml(String(auth_uid))}</span>
                        <button class="icon-btn" onclick="copyUid('${escapeAttr(String(auth_uid))}')" title="Copy UID">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </div>

                    <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                        <span style="font-size:11px;font-weight:700;color:var(--text-dim);width:90px;text-transform:uppercase;">Password</span>
                        <span style="flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;color:#ffb84d;">${escapeHtml(pwdShown)}</span>
                        <button class="icon-btn" onclick="togglePwd('${escapeAttr(uid)}')" title="Toggle">
                            <i class="fa-solid ${eyeIcon}"></i>
                        </button>
                        <button class="icon-btn" onclick="copyUid('${escapeAttr(password)}')" title="Copy Password">
                            <i class="fa-regular fa-copy"></i>
                        </button>
                    </div>

                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                        <div style="padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                            <div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Status</div>
                            <div style="font-size:13px;color:${status.includes('PAUSED') ? '#ffb84d' : '#00ffc8'};font-weight:700;">${escapeHtml(status)}</div>
                        </div>
                        <div style="padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                            <div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Level / Region</div>
                            <div style="font-size:13px;color:#fff;font-weight:700;">L${level} • ${escapeHtml(region)}</div>
                        </div>
                        <div style="padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                            <div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Mode</div>
                            <div style="font-size:13px;color:#c084fc;font-weight:700;">${escapeHtml(mode)}</div>
                        </div>
                        <div style="padding:10px 14px;background:rgba(0,0,0,0.35);border-radius:10px;border:1px solid rgba(168,85,247,0.15);">
                            <div style="font-size:10px;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:4px;">Matches / EXP</div>
                            <div style="font-size:13px;color:#fff;font-weight:700;">${matches} • ${Number(exp).toLocaleString()}</div>
                        </div>
                    </div>

                    <div style="padding:10px 14px;background:rgba(0,255,200,0.08);border-radius:10px;border:1px solid rgba(0,255,200,0.25);">
                        <div style="font-size:10px;font-weight:700;color:var(--accent-cyan);text-transform:uppercase;margin-bottom:4px;">JSON File</div>
                        <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:#fff;">${escapeHtml(json_file)}</div>
                    </div>

                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
                        <button class="btn btn-secondary" onclick="refreshManageAccount('${escapeAttr(uid)}')">
                            <i class="fa-solid fa-arrows-rotate"></i> Refresh
                        </button>
                        <button class="btn btn-secondary" onclick="restartManageAccount('${escapeAttr(uid)}')">
                            <i class="fa-solid fa-rotate-right"></i> Restart
                        </button>
                        <button class="btn btn-secondary" onclick="togglePauseAccount('${escapeAttr(uid)}')">
                            <i class="fa-solid fa-${state.is_paused ? 'play' : 'pause'}"></i> ${state.is_paused ? 'Resume' : 'Pause'}
                        </button>
                        <button class="btn btn-warn" onclick="deleteManagedAccount('${escapeAttr(uid)}', '${escapeAttr(auth_uid)}')">
                            <i class="fa-solid fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            `;
        } catch (err) {
            viewer.innerHTML = '<div class="empty-state" style="padding:40px 20px"><i class="fa-solid fa-triangle-exclamation"></i><p>Network error</p></div>';
        }
    }

    function togglePwd(uid) {
        _showPwd[uid] = !_showPwd[uid];
        viewManageAccount(uid);
    }

    async function copyJsonData(uid) {
        try {
            const r = await fetch('/api/accounts/manage_view?uid=' + encodeURIComponent(uid));
            const d = await r.json();
            if (d.status === 'ok' && d.data) {
                const json = JSON.stringify(d.data, null, 2);
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(json);
                    showToast('JSON copied', 'success');
                }
            }
        } catch (e) { showToast('Copy failed', 'error'); }
    }

    async function deleteManagedAccount(uid, auth_uid) {
        if (!confirm(`Delete account ${uid} AND its JSON file? This cannot be undone.`)) return;
        try {
            const r = await fetch('/api/account/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid, auth_uid })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast('Account + JSON file removed', 'success');
                loadManageAccounts();
                fetchStats();
            } else showToast(d.error || 'Delete failed', 'error');
        } catch (e) { showToast('Network error', 'error'); }
    }

    async function refreshManageAccount(uid) {
        try {
            await fetch('/api/account/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            showToast('Refreshing...', 'info');
            setTimeout(() => viewManageAccount(uid), 1200);
        } catch (e) {}
    }

    async function restartManageAccount(uid) {
        try {
            await fetch('/api/account/restart', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            showToast('Restarting...', 'info');
        } catch (e) {}
    }

    async function togglePauseAccount(uid) {
        try {
            const r = await fetch('/api/account/pause', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast(d.is_paused ? 'Paused' : 'Resumed', d.is_paused ? 'warning' : 'success');
                viewManageAccount(uid);
                fetchStats();
            }
        } catch (e) {}
    }

    async function deleteAccount(uid, authUid = '') {
        if (!confirm(`Remove account UID ${uid} and its JSON file?`)) return;
        try {
            const r = await fetch('/api/account/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid, auth_uid: authUid })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast('Account removed', 'info');
                fetchStats();
            } else showToast('Error', 'error');
        } catch (err) { showToast('Network error', 'error'); }
    }

    async function refreshAccountInfo(uid) {
        showToast('Refreshing...', 'info');
        try {
            await fetch('/api/account/refresh', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            setTimeout(fetchStats, 1200);
        } catch (e) {}
    }

    async function restartAccount(uid) {
        showToast('Restarting...', 'info');
        try {
            await fetch('/api/account/restart', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            setTimeout(fetchStats, 1500);
        } catch (e) {}
    }

    async function changeMode(uid, newMode) {
        try {
            const r = await fetch('/api/account/mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid, mode: newMode })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast(`Mode → ${newMode}`, 'success');
                fetchStats();
            } else showToast('Failed', 'error');
        } catch (e) { showToast('Network error', 'error'); }
    }

    async function togglePauseAccountCard(uid) {
        try {
            const r = await fetch('/api/account/pause', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ uid })
            });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast(d.is_paused ? 'Paused' : 'Resumed', d.is_paused ? 'warning' : 'success');
                fetchStats();
            }
        } catch (err) {}
    }

    async function togglePauseAll() {
        try {
            const r = await fetch('/api/account/pause_all', { method: 'POST' });
            const d = await r.json();
            if (d.status === 'ok') {
                showToast(d.all_paused ? 'All PAUSED' : 'All RESUMED', d.all_paused ? 'warning' : 'success');
                fetchStats();
            }
        } catch (err) {}
    }

    async function clearLogs() {
        try {
            await fetch('/api/logs/clear', { method: 'POST' });
            cachedLogs = [];
            document.getElementById('console-stream').innerHTML = '';
            showToast('Console cleared', 'info');
        } catch (e) {}
    }

    function copyUid(uid) {
        if (!uid) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(uid).then(() => showToast('Copied: ' + uid, 'success'));
        } else showToast('UID: ' + uid, 'info');
    }

    function manualRefresh() { fetchStats(); showToast('Refreshed', 'info'); }

    function setFilter(filter, btn) {
        activeFilter = filter;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
        filterAccounts();
    }

    function filterAccounts() {
        const query = (document.getElementById('account-search-input').value || '').toLowerCase().trim();
        document.querySelectorAll('.acc-card').forEach(card => {
            const uid = (card.dataset.uid || '').toLowerCase();
            const nick = (card.dataset.nick || '').toLowerCase();
            const status = (card.dataset.status || '').toLowerCase();
            const isPaused = card.dataset.isPaused === '1';
            const matchesQuery = !query || uid.includes(query) || nick.includes(query);
            let matchesFilter = true;
            if (activeFilter === 'in_match') matchesFilter = (status.includes('in_match') || status.includes('match')) && !isPaused;
            else if (activeFilter === 'online') matchesFilter = (status.includes('online') || status.includes('searching')) && !isPaused;
            else if (activeFilter === 'paused') matchesFilter = isPaused || status.includes('paused');
            card.style.display = (matchesQuery && matchesFilter) ? 'block' : 'none';
        });
    }

    function switchMobileTab(tab, btn) {
        document.querySelectorAll('.mobile-nav-item').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
        const tabs = ['tab-accounts', 'tab-console'];
        tabs.forEach(t => document.getElementById(t).classList.remove('active-tab'));
        if (tab === 'accounts') document.getElementById('tab-accounts').classList.add('active-tab');
        else if (tab === 'console') document.getElementById('tab-console').classList.add('active-tab');
    }

    function setLogFilter(filter, btn) {
        activeLogFilter = filter;
        document.querySelectorAll('.console-pill').forEach(b => b.classList.remove('active'));
        if (btn) btn.classList.add('active');
        renderLogs(cachedLogs);
    }

    function toggleAutoScroll() {
        autoScrollEnabled = !autoScrollEnabled;
        document.getElementById('btn-autoscroll').classList.toggle('active', autoScrollEnabled);
        if (autoScrollEnabled) jumpToBottom();
    }

    function jumpToBottom() {
        const stream = document.getElementById('console-stream');
        if (stream) stream.scrollTop = stream.scrollHeight;
    }

    function getModeBadge(selectedMode, actualMode, level) {
        if (selectedMode === 'LONE_WOLF') return `<span class="mode-badge lw"><i class="fa-solid fa-shield-halved"></i> LW</span>`;
        if (selectedMode === 'BR') return `<span class="mode-badge br"><i class="fa-solid fa-crosshairs"></i> BR</span>`;
        if (level < 3) return `<span class="mode-badge auto"><i class="fa-solid fa-wand-magic-sparkles"></i> AUTO → BR</span>`;
        return `<span class="mode-badge auto"><i class="fa-solid fa-wand-magic-sparkles"></i> AUTO → LW</span>`;
    }

    function formatFullTime(sec) {
        sec = Math.max(0, Math.floor(sec || 0));
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = sec % 60;
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function formatMinutes(sec) {
        sec = Math.max(0, Math.floor(sec || 0));
        const totalMin = Math.floor(sec / 60);
        const secLeft = sec % 60;
        if (totalMin >= 60) {
            const h = Math.floor(totalMin / 60);
            const m = totalMin % 60;
            return `${h}h ${m}m`;
        }
        if (totalMin <= 0) return `${secLeft}s`;
        return `${totalMin}m ${secLeft}s`;
    }

    function getLiveUptime(uid, baselineSeconds) {
        const now = Date.now();
        if (!uptimeBaselines[uid]) {
            uptimeBaselines[uid] = { baseline: baselineSeconds, tickAt: now };
            return baselineSeconds;
        }
        const b = uptimeBaselines[uid];
        if (baselineSeconds > b.baseline) {
            b.baseline = baselineSeconds;
            b.tickAt = now;
            return baselineSeconds;
        }
        const elapsed = Math.floor((now - b.tickAt) / 1000);
        return b.baseline + elapsed;
    }

    function renderAccounts(accounts) {
        const container = document.getElementById('accounts-container');
        document.getElementById('badge-acc-count').innerText = `${accounts.length} Active`;

        const allPaused = accounts.length > 0 && accounts.every(a => a.is_paused || a.status === 'PAUSED');
        const gpBtn = document.getElementById('btn-global-pause');
        if (gpBtn) {
            if (allPaused) {
                gpBtn.className = 'btn-pause-all all-paused';
                gpBtn.innerHTML = '<i class="fa-solid fa-play"></i> <span>Resume All</span>';
            } else {
                gpBtn.className = 'btn-pause-all';
                gpBtn.innerHTML = '<i class="fa-solid fa-pause"></i> <span>Pause All</span>';
            }
        }

        if (accounts.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="grid-column:1/-1">
                    <i class="fa-solid fa-ghost"></i>
                    <p>No accounts running. Use one of the 5 options above to start.</p>
                </div>`;
            return;
        }

        if (container.querySelector('.empty-state')) container.innerHTML = '';

        const currentUids = new Set(accounts.map(a => String(a.uid)));
        container.querySelectorAll('.acc-card').forEach(card => {
            if (!currentUids.has(card.dataset.uid)) card.remove();
        });

        accounts.forEach(acc => {
            const uid = String(acc.uid);
            const gainedExp = acc.gained_exp || 0;
            const isPaused = Boolean(acc.is_paused || acc.status === 'PAUSED');
            const baselineSec = Math.floor(acc.uptime_seconds || 0);
            const uptimeSec = getLiveUptime(uid, baselineSec);
            const status = isPaused ? 'PAUSED' : (acc.status || 'ONLINE');
            const statusClass = isPaused ? 'paused' : (status.includes('IN_MATCH') ? 'in_match' : (status.includes('SEARCHING') ? 'searching' : (status.includes('ONLINE') ? 'online' : 'error')));
            const statusText = isPaused ? 'PAUSED' : (status.includes('IN_MATCH') ? `In Match (${acc.active_matches || 1})` : status);

            const lvl = Math.max(1, parseInt(acc.level) || 1);
            const nextLvl = Math.min(100, lvl + 1);
            const baseExp = EXP_TABLE[lvl] !== undefined ? EXP_TABLE[lvl] : 0;
            const targetExp = EXP_TABLE[nextLvl] !== undefined ? EXP_TABLE[nextLvl] : (baseExp + 50000);
            const neededForLevel = Math.max(1, targetExp - baseExp);
            const earnedInLevel = Math.max(0, (acc.current_exp || 0) - baseExp);
            const remainingExp = Math.max(0, targetExp - (acc.current_exp || 0));
            const progressPct = lvl >= 100 ? 100 : Math.min(100, Math.max(0, (earnedInLevel / neededForLevel) * 100));

            const selectedMode = acc.selected_mode || 'AUTO';
            const modeBadge = getModeBadge(selectedMode, acc.mode, lvl);

            let card = document.getElementById(`acc-card-${uid}`);
            if (!card) {
                card = document.createElement('div');
                card.id = `acc-card-${uid}`;
                card.className = 'acc-card';
                card.dataset.uid = uid;
                container.appendChild(card);
            }
            card.dataset.nick = acc.nickname || '';
            card.dataset.status = statusClass;
            card.dataset.isPaused = isPaused ? '1' : '0';

            card.innerHTML = `
                <div class="acc-header">
                    <div class="acc-identity">
                        <div class="acc-avatar">
                            <i class="fa-solid fa-gamepad"></i>
                            <span class="level-badge">L${lvl}</span>
                        </div>
                        <div class="acc-details">
                            <h4>${escapeHtml(acc.nickname)} <span class="region-tag">${escapeHtml(acc.region || 'BD')}</span> ${modeBadge}</h4>
                            <div class="acc-uid">
                                <span>UID: ${escapeHtml(uid)}</span>
                                <button class="btn-copy" onclick="copyUid('${escapeAttr(uid)}')" title="Copy UID"><i class="fa-regular fa-copy"></i></button>
                            </div>
                        </div>
                    </div>
                    <div class="status-pill ${statusClass}">
                        <span class="radar-dot"></span>
                        <span>${escapeHtml(statusText)}</span>
                    </div>
                </div>

                <div class="runtime-strip">
                    <div class="rt-left">
                        <div class="rt-icon"><i class="fa-solid fa-clock"></i></div>
                        <div class="rt-info">
                            <span class="rt-label">Running Time</span>
                            <span class="rt-value" data-uptime-uid="${escapeAttr(uid)}" data-baseline-sec="${baselineSec}">${formatFullTime(uptimeSec)}</span>
                        </div>
                    </div>
                    <div class="rt-minutes">
                        <span class="rt-min-label">Duration</span>
                        <span class="rt-min-value" data-uptime-min-uid="${escapeAttr(uid)}">${formatMinutes(uptimeSec)}</span>
                    </div>
                </div>

                <div class="exp-strip">
                    <div class="exp-col"><span>Initial</span><strong>${(acc.initial_exp || 0).toLocaleString()}</strong></div>
                    <div class="exp-col"><span>Current</span><strong>${(acc.current_exp || 0).toLocaleString()}</strong></div>
                    <div class="exp-col"><span>Gain</span><strong class="exp-gained-highlight">+${gainedExp.toLocaleString()}</strong></div>
                </div>

                <div class="card-progress">
                    <div class="progress-header">
                        <span class="prog-level-tag">
                            <i class="fa-solid fa-angles-up" style="color:var(--accent-cyan);"></i>
                            L${lvl} → <strong style="color:var(--accent-cyan);">L${nextLvl}</strong>
                        </span>
                        <span class="prog-needed-badge">${remainingExp.toLocaleString()} EXP left</span>
                    </div>
                    <div class="progress-track">
                        <div class="progress-fill" style="width: ${progressPct.toFixed(1)}%"></div>
                    </div>
                    <div class="progress-sub">
                        <span>${earnedInLevel.toLocaleString()} / ${neededForLevel.toLocaleString()}</span>
                        <span class="prog-pct-pill">${progressPct.toFixed(1)}%</span>
                    </div>
                </div>

                <div class="mode-selector-row">
                    <label><i class="fa-solid fa-gamepad"></i> Mode</label>
                    <select class="mode-select" onchange="changeMode('${escapeAttr(uid)}', this.value)">
                        <option value="AUTO" ${selectedMode === 'AUTO' ? 'selected' : ''}>⚡ AUTO (BR → LW)</option>
                        <option value="LONE_WOLF" ${selectedMode === 'LONE_WOLF' ? 'selected' : ''}>🛡 Lone Wolf</option>
                        <option value="BR" ${selectedMode === 'BR' ? 'selected' : ''}>🎯 Battle Royale</option>
                    </select>
                </div>

                <div class="acc-footer">
                    <span>Last: ${escapeHtml(acc.last_match_time || 'Running...')}</span>
                    <div class="acc-btns">
                        <button class="icon-btn ${isPaused ? 'btn-resume' : 'btn-pause'}" onclick="togglePauseAccountCard('${escapeAttr(uid)}')" title="${isPaused ? 'Resume' : 'Pause'}">
                            <i class="fa-solid ${isPaused ? 'fa-play' : 'fa-pause'}"></i>
                        </button>
                        <button class="icon-btn" onclick="restartAccount('${escapeAttr(uid)}')" title="Restart"><i class="fa-solid fa-rotate-right"></i></button>
                        <button class="icon-btn" onclick="refreshAccountInfo('${escapeAttr(uid)}')" title="Refresh"><i class="fa-solid fa-arrows-rotate"></i></button>
                        <button class="icon-btn danger" onclick="deleteAccount('${escapeAttr(uid)}', '${escapeAttr(acc.auth_uid || '')}')" title="Delete"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </div>
            `;
        });

        filterAccounts();
    }

    function tickUptimes() {
        document.querySelectorAll('[data-uptime-uid]').forEach(el => {
            const uid = el.getAttribute('data-uptime-uid');
            const baseline = parseInt(el.dataset.baselineSec || '0', 10) || (uptimeBaselines[uid]?.baseline || 0);
            const liveSec = getLiveUptime(uid, baseline);
            el.textContent = formatFullTime(liveSec);

            const minEl = document.querySelector(`[data-uptime-min-uid="${uid}"]`);
            if (minEl) minEl.textContent = formatMinutes(liveSec);
        });
    }
    setInterval(tickUptimes, 1000);

    function renderLogs(logs) {
        const stream = document.getElementById('console-stream');
        let filtered = logs;
        if (activeLogFilter === 'match') filtered = logs.filter(l => l.message.includes('Match') || l.message.includes('⚔'));
        else if (activeLogFilter === 'success') filtered = logs.filter(l => l.level === 'success' || l.message.includes('EXP'));
        else if (activeLogFilter === 'error') filtered = logs.filter(l => l.level === 'error' || l.level === 'warning');

        stream.innerHTML = filtered.map(log => {
            const lvl = log.level || 'info';
            return `<div class="log-entry"><span class="log-ts">[${log.time || '00:00:00'}]</span><span class="log-txt ${lvl}">${escapeHtml(log.message)}</span></div>`;
        }).join('');

        if (autoScrollEnabled) jumpToBottom();
    }

    async function fetchStats() {
        try {
            const r = await fetch('/api/stats', { cache: 'no-store' });
            const d = await r.json();

            document.getElementById('stat-accs').innerText = d.total_accounts || 0;
            document.getElementById('stat-started').innerText = d.total_matches_started || 0;
            document.getElementById('stat-done').innerText = d.total_matches || 0;
            document.getElementById('stat-exp').innerText = '+' + (d.total_gained_exp || 0).toLocaleString();
            document.getElementById('stat-files').innerText = d.bot_files_count || 0;

            const modeBadge = document.getElementById('brand-active-mode');
            if (modeBadge) modeBadge.innerText = `MODE: ${d.active_mode || 'IDLE'}`;

            cachedAccounts = d.accounts || [];
            renderAccounts(cachedAccounts);

            cachedLogs = d.logs || [];
            renderLogs(cachedLogs);
        } catch (err) {}
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
    function escapeAttr(s) { return escapeHtml(s); }

    const EXP_TABLE = {
        1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
        9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
        16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
        23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
        30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
        37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
        44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
        51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
        58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
        64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
        70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
        76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
        82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
        88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
        94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
        100: 32032884
    };

    setInterval(() => {
        const sec = Math.floor((Date.now() - localClientTime) / 1000);
        const h = String(Math.floor(sec / 3600)).padStart(2, '0');
        const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        const el = document.getElementById('brand-uptime');
        if (el) el.innerText = `${h}:${m}:${s}`;
    }, 1000);

    fetchStats();
    setInterval(fetchStats, 2500);
</script>
</body>
</html>
"""


# ============================================================
#  HTTP HANDLERS
# ============================================================

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    uptime_sec = max(1, int(time.time() - bot_state.start_time))
    total_gained = bot_state.total_gained_exp
    exp_per_hour = int((total_gained / uptime_sec) * 3600)
    total_active_matches = sum(acc.get("active_matches", 0) for acc in accounts_data)

    for acc in accounts_data:
        uid_k = str(acc.get("uid", ""))
        acc["uptime_seconds"] = bot_state.get_account_uptime(uid_k)
        acc["is_paused"] = bot_state.is_paused(uid_k)

    bot_files_count = 0
    try:
        d = "bot_accounts"
        if os.path.isdir(d):
            bot_files_count = sum(
                1 for fn in os.listdir(d)
                if fn.startswith("MAHUR_") and fn.endswith(".json")
            )
    except Exception:
        pass

    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_matches_started": getattr(bot_state, "matches_started", 0),
        "total_active_matches": total_active_matches,
        "total_gained_exp": total_gained,
        "exp_per_hour": exp_per_hour,
        "accounts": accounts_data,
        "logs": bot_state.logs[-80:],
        "uptime": uptime_sec,
        "bot_files_count": bot_files_count,
        "active_mode": getattr(bot_state, "active_mode", "IDLE"),
        "creating": getattr(bot_state, "creating", False),
        "create_progress": getattr(bot_state, "create_progress", [])[-40:],
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        mode = str(data.get("mode", "AUTO")).strip().upper()
        if mode not in ("AUTO", "LONE_WOLF", "BR"):
            mode = "AUTO"

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})
            if uid in bot_state.account_workers:
                try: bot_state.account_workers[uid].cancel()
                except Exception: pass
                bot_state.account_workers.pop(uid, None)
            existing = [acc for acc in existing if str(acc.get("uid", "")) != uid]
            existing.append({"uid": uid, "password": pwd, "mode": mode})
            identifier = uid
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})
            tok_key = token[:16]
            for k in list(bot_state.account_workers.keys()):
                if k == tok_key or k.startswith(tok_key[:10]) or tok_key.startswith(k[:10]):
                    try: bot_state.account_workers[k].cancel()
                    except Exception: pass
                    bot_state.account_workers.pop(k, None)
            existing = [acc for acc in existing if acc.get("token", "") != token]
            existing.append({"token": token, "mode": mode})
            identifier = f"Token_{token[:8]}..."
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {identifier} [mode={mode}]", "success")
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_change_mode(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        mode = str(data.get("mode", "AUTO")).strip().upper()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        if mode not in ("AUTO", "LONE_WOLF", "BR"):
            return web.json_response({"status": "error", "error": "Invalid mode"})

        updated = bot_state.set_account_mode(uid, mode)

        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                candidates = {uid}
                if uid in bot_state.auth_to_game_id:
                    candidates.add(str(bot_state.auth_to_game_id[uid]))
                if uid in bot_state.game_to_auth_id:
                    candidates.add(str(bot_state.game_to_auth_id[uid]))
                for acc in existing:
                    acc_uid = str(acc.get("uid", "")).strip()
                    acc_tok = str(acc.get("token", "")).strip()
                    if acc_uid in candidates:
                        acc["mode"] = mode
                    elif acc_tok and (acc_tok in candidates or any(c.startswith(acc_tok[:10]) for c in candidates)):
                        acc["mode"] = mode
                with open(accounts_file, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
            except Exception as e:
                print(f"Mode save error: {e}")

        if "on_mode_change" in bot_state.refresh_callbacks:
            try:
                await bot_state.refresh_callbacks["on_mode_change"](uid, mode)
            except Exception:
                pass
        return web.json_response({"status": "ok", "updated": updated, "mode": mode})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        req_uid = str(data.get("uid", "")).strip()
        req_auth_uid = str(data.get("auth_uid", "")).strip()
        if not req_uid and not req_auth_uid:
            return web.json_response({"status": "error", "error": "UID required"})

        candidate_ids = set()
        if req_uid: candidate_ids.add(req_uid)
        if req_auth_uid: candidate_ids.add(req_auth_uid)

        for cid in list(candidate_ids):
            if cid in bot_state.game_to_auth_id:
                candidate_ids.add(str(bot_state.game_to_auth_id[cid]))
            if cid in bot_state.auth_to_game_id:
                candidate_ids.add(str(bot_state.auth_to_game_id[cid]))

        target_tokens = set()
        for cid in list(candidate_ids):
            acc_info = bot_state.accounts.get(cid, {})
            if acc_info:
                if acc_info.get("auth_uid"): candidate_ids.add(str(acc_info["auth_uid"]))
                if acc_info.get("uid"): candidate_ids.add(str(acc_info["uid"]))
                t = acc_info.get("token") or acc_info.get("access_token")
                if t: target_tokens.add(str(t))
        for cid in list(candidate_ids):
            creds = bot_state.account_credentials.get(cid, {})
            if creds:
                if creds.get("auth_uid"): candidate_ids.add(str(creds["auth_uid"]))
                if creds.get("account_id"): candidate_ids.add(str(creds["account_id"]))
                t = creds.get("token") or creds.get("access_token") or creds.get("auth_token")
                if t: target_tokens.add(str(t))

        deleted_files = []
        bot_accounts_dir = "bot_accounts"
        if os.path.isdir(bot_accounts_dir):
            for fn in os.listdir(bot_accounts_dir):
                if not (fn.startswith("MAHUR_") and fn.endswith(".json")):
                    continue
                fp = os.path.join(bot_accounts_dir, fn)
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        fdata = json.load(f)
                    f_uid = str(fdata.get("uid", ""))
                    f_acc_id = str(fdata.get("account_id", ""))
                    if f_uid in candidate_ids or f_acc_id in candidate_ids:
                        os.remove(fp)
                        deleted_files.append(fn)
                except Exception:
                    continue

        token_cache_file = "token_cache.json"
        if os.path.exists(token_cache_file):
            try:
                with open(token_cache_file, "r", encoding="utf-8") as f:
                    tcache = json.load(f)
                dirty = False
                for k, v in list(tcache.items()):
                    k_str = str(k)
                    v_acc_id = str(v.get("account_id", ""))
                    v_auth_uid = str(v.get("auth_uid", ""))
                    if k_str in candidate_ids or v_acc_id in candidate_ids or v_auth_uid in candidate_ids:
                        candidate_ids.add(k_str)
                        if v_acc_id: candidate_ids.add(v_acc_id)
                        if v_auth_uid: candidate_ids.add(v_auth_uid)
                        del tcache[k]
                        dirty = True
                if dirty:
                    with open(token_cache_file, "w", encoding="utf-8") as f:
                        json.dump(tcache, f, indent=2)
            except Exception:
                pass

        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                new_existing = []
                for acc in existing:
                    acc_uid = str(acc.get("uid", "")).strip()
                    acc_tok = str(acc.get("token", "")).strip()
                    is_match = False
                    if acc_uid and acc_uid in candidate_ids: is_match = True
                    if acc_tok and (acc_tok in candidate_ids or acc_tok in target_tokens): is_match = True
                    for tok in target_tokens:
                        if acc_tok and (acc_tok.startswith(tok[:16]) or tok.startswith(acc_tok[:16])):
                            is_match = True
                    if not is_match:
                        new_existing.append(acc)
                with open(accounts_file, "w", encoding="utf-8") as f:
                    json.dump(new_existing, f, indent=2)
            except Exception:
                pass

        for cid in candidate_ids:
            bot_state.accounts.pop(cid, None)
            bot_state.account_credentials.pop(cid, None)
            bot_state.auth_to_game_id.pop(cid, None)
            bot_state.game_to_auth_id.pop(cid, None)
            bot_state.account_token_map.pop(cid, None)
            bot_state.paused_accounts.discard(cid)

        cancelled_keys = []
        for k, worker in list(bot_state.account_workers.items()):
            k_str = str(k)
            should_cancel = False
            if k_str in candidate_ids: should_cancel = True
            for tok in target_tokens:
                if k_str == tok[:16] or tok.startswith(k_str[:10]): should_cancel = True
            if should_cancel:
                try: worker.cancel()
                except Exception: pass
                cancelled_keys.append(k)
        for k in cancelled_keys:
            bot_state.account_workers.pop(k, None)
        for cid in candidate_ids:
            bot_state.close_writers_for_account(cid)

        if "on_account_deleted" in bot_state.refresh_callbacks:
            try:
                asyncio.create_task(bot_state.refresh_callbacks["on_account_deleted"](list(candidate_ids)))
            except Exception:
                pass

        target_repr = req_uid or req_auth_uid
        bot_state.log(f"Account {target_repr} deleted (+{len(deleted_files)} JSON).", "warning", target_repr)
        bot_state.recalc_totals()
        return web.json_response({"status": "ok", "deleted": list(candidate_ids), "deleted_files": deleted_files})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_restart_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_restart_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_restart_account"](uid))
        elif "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_clear_logs(request: web.Request) -> web.Response:
    bot_state.logs.clear()
    return web.json_response({"status": "ok"})


async def handle_toggle_pause(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        is_paused = bot_state.toggle_pause(uid)
        return web.json_response({"status": "ok", "is_paused": is_paused})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_toggle_pause_all(request: web.Request) -> web.Response:
    try:
        paused_state = bot_state.toggle_pause_all()
        return web.json_response({"status": "ok", "all_paused": paused_state})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_create_auto(request: web.Request) -> web.Response:
    return web.json_response({"ok": False, "error": "Auto-create endpoint not available in dashboard_server.py."})


async def handle_create_guild(request: web.Request) -> web.Response:
    return web.json_response({"ok": False, "error": "Guild-create endpoint not available in dashboard_server.py."})


# ============================================================
#  BOT FILES
# ============================================================

def _list_bot_files() -> List[dict]:
    out = []
    d = "bot_accounts"
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        if not (fn.startswith("MAHUR_") and fn.endswith(".json")):
            continue
        fp = os.path.join(d, fn)
        try:
            st = os.stat(fp)
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            out.append({
                "filename": fn,
                "uid": str(data.get("uid", "")),
                "account_id": str(data.get("account_id", "")),
                "nickname": data.get("nickname", ""),
                "password": data.get("password", ""),
                "region": data.get("region", ""),
                "level": data.get("level", 1),
                "exp": data.get("exp", 0),
                "mode": data.get("mode", "AUTO"),
                "status": data.get("status", "ACTIVE"),
                "size": st.st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                "mtime": st.st_mtime,
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _load_bot_file(filename: str) -> Optional[dict]:
    if not filename.startswith("MAHUR_") or not filename.endswith(".json"):
        return None
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    fp = os.path.join("bot_accounts", filename)
    if not os.path.exists(fp): return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _delete_bot_file(filename: str) -> bool:
    if not filename.startswith("MAHUR_") or not filename.endswith(".json"):
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    fp = os.path.join("bot_accounts", filename)
    if os.path.exists(fp):
        try:
            os.remove(fp)
            return True
        except Exception:
            return False
    return False


async def handle_bot_files_list(request: web.Request) -> web.Response:
    try:
        files = _list_bot_files()
        return web.json_response({"status": "ok", "count": len(files), "files": files})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_bot_files_view(request: web.Request) -> web.Response:
    fname = request.query.get("file", "").strip()
    if not fname:
        return web.json_response({"status": "error", "error": "file required"}, status=400)
    data = _load_bot_file(fname)
    if not data:
        return web.json_response({"status": "error", "error": "not found"}, status=404)
    return web.json_response({"status": "ok", "file": fname, "data": data})


async def handle_bot_files_delete(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    fname = str(body.get("file", "")).strip()
    if not fname:
        return web.json_response({"status": "error", "error": "file required"}, status=400)
    ok = _delete_bot_file(fname)
    if ok:
        bot_state.log(f"[BOT-FILES] Deleted {fname}", "warning")
    return web.json_response({"status": "ok" if ok else "error"})


async def handle_bot_files_download(request: web.Request) -> web.Response:
    fname = request.query.get("file", "").strip()
    if not fname or not fname.startswith("MAHUR_") or not fname.endswith(".json"):
        return web.Response(status=400, text="invalid filename")
    if "/" in fname or "\\" in fname or ".." in fname:
        return web.Response(status=400, text="invalid filename")
    fp = os.path.join("bot_accounts", fname)
    if not os.path.exists(fp):
        return web.Response(status=404, text="not found")
    return web.FileResponse(fp, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


async def handle_bot_files_download_all(request: web.Request) -> web.Response:
    import zipfile, io as _io
    try:
        buf = _io.BytesIO()
        added = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            d = "bot_accounts"
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    if not (fn.startswith("MAHUR_") and fn.endswith(".json")):
                        continue
                    fp = os.path.join(d, fn)
                    if os.path.exists(fp):
                        zf.write(fp, arcname=fn)
                        added += 1
        if added == 0:
            return web.json_response({"status": "error", "error": "no files"})
        buf.seek(0)
        fname_out = f"MAHUR_BOTS_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        return web.Response(
            body=buf.read(),
            content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname_out}"'}
        )
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_accounts_manage_list(request: web.Request) -> web.Response:
    try:
        accs = []
        seen = set()
        for uid, a in bot_state.accounts.items():
            seen.add(uid)
            auth_uid = a.get("auth_uid", "")
            if auth_uid: seen.add(auth_uid)
            json_fn = ""
            for f in _list_bot_files():
                if f["uid"] == uid or f["account_id"] == uid or f["uid"] == auth_uid:
                    json_fn = f["filename"]
                    break
            accs.append({
                "uid": uid, "auth_uid": auth_uid,
                "nickname": a.get("nickname", ""), "region": a.get("region", ""),
                "level": a.get("level", 1), "exp": a.get("current_exp", 0),
                "gained_exp": a.get("gained_exp", 0), "matches": a.get("matches_played", 0),
                "status": a.get("status", "UNKNOWN"), "is_paused": bool(a.get("is_paused", False)),
                "json_file": json_fn, "uptime_seconds": bot_state.get_account_uptime(uid),
                "last_match_time": a.get("last_match_time", "—"),
            })
        for f in _list_bot_files():
            if f["uid"] in seen or f["account_id"] in seen:
                continue
            accs.append({
                "uid": f.get("uid") or f.get("account_id"),
                "auth_uid": f.get("uid", ""),
                "nickname": f.get("nickname", ""), "region": f.get("region", ""),
                "level": f.get("level", 1), "exp": f.get("exp", 0),
                "gained_exp": 0, "matches": 0,
                "status": f.get("status", "IDLE"), "is_paused": False,
                "json_file": f.get("filename", ""), "uptime_seconds": 0,
                "last_match_time": "—",
            })
        return web.json_response({"status": "ok", "accounts": accs})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_accounts_manage_view(request: web.Request) -> web.Response:
    uid = request.query.get("uid", "").strip()
    if not uid:
        return web.json_response({"status": "error", "error": "uid required"}, status=400)
    json_data = None
    json_file = ""
    for f in _list_bot_files():
        if f["uid"] == uid or f["account_id"] == uid:
            json_data = _load_bot_file(f["filename"])
            json_file = f["filename"]
            break
    state = bot_state.accounts.get(uid)
    if not json_data and not state:
        return web.json_response({"status": "error", "error": "not found"}, status=404)
    return web.json_response({
        "status": "ok",
        "data": {"uid": uid, "json_file": json_file, "json_data": json_data, "state": state}
    })


# ============================================================
#  START WEB DASHBOARD
# ============================================================

async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/favicon.ico", favicon_handler)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/mode", handle_change_mode)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/restart", handle_restart_account)
    app.router.add_post("/api/account/pause", handle_toggle_pause)
    app.router.add_post("/api/account/pause_all", handle_toggle_pause_all)
    app.router.add_post("/api/logs/clear", handle_clear_logs)
    app.router.add_post("/api/create_auto", handle_create_auto)
    app.router.add_post("/api/create_guild", handle_create_guild)
    app.router.add_get ("/api/bot_files",              handle_bot_files_list)
    app.router.add_get ("/api/bot_files/view",         handle_bot_files_view)
    app.router.add_post("/api/bot_files/delete",       handle_bot_files_delete)
    app.router.add_get ("/api/bot_files/download",     handle_bot_files_download)
    app.router.add_get ("/api/bot_files/download_all", handle_bot_files_download_all)
    app.router.add_get ("/api/accounts/manage_list",   handle_accounts_manage_list)
    app.router.add_get ("/api/accounts/manage_view",   handle_accounts_manage_view)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] MAHIR v3.0 Dashboard → http://localhost:{port}\033[0m")
    return runner


async def _standalone_main():
    runner = await start_web_dashboard(host="0.0.0.0", port=5000)
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(_standalone_main())
    except KeyboardInterrupt:
        print("Stopped.")