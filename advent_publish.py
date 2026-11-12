#!/usr/bin/env python3
"""Tespit Adventskalender 2026: publishes door N's codes at a secret random time (GitHub Actions, every 10 min).

Door N belongs to 1–24 December (Europe/Berlin). Its opening time lies between 08:00 and 20:00 and comes from
HMAC-SHA256(ADVENT_SEED, "2026-12-DD"), so nobody knows it in advance. From then on advent/2026/door-NN.json holds
the prize and both platform codes, each sealed with AES-256-GCM (key ADVENT_KEY, only the app knows it; AAD
"door-NN-ios" / "door-NN-android"). The codes live only in the secret ADVENT_CODES until then:
{"1": {"ios": "...", "android": "..."}, ..., "24": {...}}.

  advent_publish.py            remove earlier days' doors; publish today's door if it is due (Actions)
  advent_publish.py --times    print the 24 opening times (needs ADVENT_SEED; never commit the output)
  advent_publish.py --check    check the three secrets; prints only short fingerprints, writes nothing
  advent_publish.py --test     write advent/test/door-01.json with dummy codes, opened now (app QA)
"""
import base64, datetime, hashlib, hmac, json, os, sys
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

YEAR = 2026
BERLIN = ZoneInfo("Europe/Berlin")
ROOT = os.path.dirname(os.path.abspath(__file__))


def prize(day: int) -> str:
    # Esat 12.11.2026: 1–9 two weeks, 10–19 one month, 20–23 three months, 24 Lifetime.
    return "lifetime" if day == 24 else "month3" if day >= 20 else "month1" if day >= 10 else "weeks2"


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


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def check(key: bytes, seed: bytes, codes: dict) -> int:
    """--check: are the three secrets complete and usable? Prints only counts and short fingerprints, never a
    code or an opening time; nothing is written."""
    problems = []
    if len(key) != 32:
        problems.append("ADVENT_KEY is not 32 bytes")
    if len(seed) < 16:
        problems.append("ADVENT_SEED is shorter than 16 bytes")
    days = [d for d in range(1, 25) if codes.get(str(d), {}).get("ios") and codes.get(str(d), {}).get("android")]
    if len(days) != 24:
        problems.append(f"ADVENT_CODES has both codes for {len(days)} of 24 doors")
    every = [codes[str(d)][p] for d in days for p in ("ios", "android")]
    if len(set(every)) != len(every):
        problems.append("ADVENT_CODES repeats a code")
    for d in days:
        for p in ("ios", "android"):
            box = seal(key, codes[str(d)][p], d, p)
            plain = AESGCM(key).decrypt(base64.b64decode(box["nonce"]), base64.b64decode(box["box"]), f"door-{d:02d}-{p}".encode())
            if plain.decode() != codes[str(d)][p]:
                problems.append(f"door {d} {p} does not round-trip")
    canonical = json.dumps({str(d): codes[str(d)] for d in days}, sort_keys=True, separators=(",", ":")).encode()
    print(f"key {fingerprint(key)} seed {fingerprint(seed)} codes {fingerprint(canonical)} doors {len(days)}")
    for p in problems:
        print(f"::error::{p}")
    print("check ok" if not problems else "check FAILED")
    return 1 if problems else 0


def stale_doors(root: str, now: datetime.datetime) -> list:
    """The door files of earlier days (Berlin): removed at midnight, so the path the app asks for never serves an old
    door again, whatever time a phone or a proxy claims (Esat 12.11.2026: „nicht manipulierbar“). Git history keeps
    them, but the app never reads it."""
    folder = f"{root}/advent/{YEAR}"
    today = now.astimezone(BERLIN).date()
    stale = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not (name.startswith("door-") and name.endswith(".json")):
            continue
        try:
            day = int(name[5:7])
        except ValueError:
            continue
        if datetime.date(YEAR, 12, day) < today:
            stale.append(f"{folder}/{name}")
    return stale


def main() -> int:
    key = bytes.fromhex(os.environ["ADVENT_KEY"].strip())
    if "--test" in sys.argv:
        now = datetime.datetime.now(BERLIN).replace(microsecond=0)
        write(f"{ROOT}/advent/test/door-01.json", door(key, 1, now, {"ios": "TESPIT-TEST-IOS", "android": "TESPIT-TEST-ANDROID"}))
        print("test door written")
        return 0
    seed = bytes.fromhex(os.environ["ADVENT_SEED"].strip())
    if "--check" in sys.argv:
        return check(key, seed, json.loads(os.environ.get("ADVENT_CODES") or "{}"))
    if "--times" in sys.argv:
        for day in range(1, 25):
            print(day, opening_time(seed, day).strftime("%H:%M"))
        return 0
    now = datetime.datetime.now(BERLIN)
    for path in stale_doors(ROOT, now):
        os.remove(path)
        print(f"removed {os.path.basename(path)}")
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
