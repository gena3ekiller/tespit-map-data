#!/usr/bin/env python3
"""Tespit Adventskalender 2026: publishes door N's codes at a secret random time (GitHub Actions, every 10 min).

Door N belongs to 1–24 December (Europe/Berlin). Its opening time lies between 08:00 and 20:00 and comes from
HMAC-SHA256(ADVENT_SEED, "2026-12-DD"), so nobody knows it in advance. From then on advent/2026/door-NN.json holds
the prize and both platform codes, each sealed with AES-256-GCM (key ADVENT_KEY, only the app knows it; AAD
"door-NN-ios" / "door-NN-android"). The codes live only in the secret ADVENT_CODES until then:
{"1": {"ios": "...", "android": "..."}, ..., "24": {...}}.

  advent_publish.py            publish today's door if it is due (Actions)
  advent_publish.py --times    print the 24 opening times (needs ADVENT_SEED; never commit the output)
  advent_publish.py --test     write advent/test/door-01.json with dummy codes, opened now (app QA)
"""
import base64, datetime, hashlib, hmac, json, os, sys
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

YEAR = 2026
BERLIN = ZoneInfo("Europe/Berlin")
ROOT = os.path.dirname(os.path.abspath(__file__))


def prize(day: int) -> str:
    return "lifetime" if day == 24 else "month3" if day >= 20 else "month1"


def opening_time(seed: bytes, day: int) -> datetime.datetime:
    digest = hmac.new(seed, f"{YEAR}-12-{day:02d}".encode(), hashlib.sha256).digest()
    minutes = int.from_bytes(digest[:8], "big") % (12 * 60)  # 08:00 .. 19:59
    return datetime.datetime(YEAR, 12, day, 8, 0, tzinfo=BERLIN) + datetime.timedelta(minutes=minutes)


def seal(key: bytes, code: str, day: int, platform: str) -> dict:
    nonce = os.urandom(12)
    box = AESGCM(key).encrypt(nonce, code.encode(), f"door-{day:02d}-{platform}".encode())
    return {"nonce": base64.b64encode(nonce).decode(), "box": base64.b64encode(box).decode()}


def door(key: bytes, day: int, opened: datetime.datetime, codes: dict) -> dict:
    return {
        "schema": 1, "year": YEAR, "day": day, "prize": prize(day),
        "openedAt": opened.isoformat(timespec="seconds"),
        "ios": seal(key, codes["ios"], day, "ios"),
        "android": seal(key, codes["android"], day, "android"),
    }


def write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")


def main() -> int:
    key = bytes.fromhex(os.environ["ADVENT_KEY"].strip())
    if "--test" in sys.argv:
        now = datetime.datetime.now(BERLIN).replace(microsecond=0)
        write(f"{ROOT}/advent/test/door-01.json", door(key, 1, now, {"ios": "TESPIT-TEST-IOS", "android": "TESPIT-TEST-ANDROID"}))
        print("test door written")
        return 0
    seed = bytes.fromhex(os.environ["ADVENT_SEED"].strip())
    if "--times" in sys.argv:
        for day in range(1, 25):
            print(day, opening_time(seed, day).strftime("%H:%M"))
        return 0
    now = datetime.datetime.now(BERLIN)
    if not (now.year == YEAR and now.month == 12 and 1 <= now.day <= 24):
        print("outside the calendar")
        return 0
    day = now.day
    path = f"{ROOT}/advent/{YEAR}/door-{day:02d}.json"
    if os.path.exists(path):
        print(f"door {day} already open")
        return 0
    opened = opening_time(seed, day)
    if now < opened:
        print(f"door {day} not due yet")  # the time itself is never printed
        return 0
    codes = json.loads(os.environ.get("ADVENT_CODES") or "{}").get(str(day))
    if not codes or not codes.get("ios") or not codes.get("android"):
        print(f"::error::no codes for door {day}")
        return 1
    write(path, door(key, day, opened, codes))
    print(f"door {day} published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
