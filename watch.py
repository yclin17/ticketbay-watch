#!/usr/bin/env python3
"""Watch Ticketbay Global for listings with >= MIN_QTY tickets and notify.

Uses the site's public JSON API (the same one the product page calls).
Run it from cron/launchd every few minutes. Standard library only.

Env vars (all optional):
  CATEGORY_ID  event id from the URL        (default 6815)
  MIN_QTY      min tickets in one listing   (default 3)
  DATES        comma-separated dates to keep, e.g. 2026-12-19,2026-12-20
  TOGETHER     "1" = only adjacent seats (default), "0" = any seats
  NTFY_TOPIC   if set, also push to https://ntfy.sh/<topic> (phone alerts)
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

API = "https://api.ticketbayglobal.com/public/products/pages"
CATEGORY_ID = int(os.environ.get("CATEGORY_ID", "6815"))
MIN_QTY = int(os.environ.get("MIN_QTY", "3"))
DATES = [d for d in os.environ.get("DATES", "").split(",") if d]
TOGETHER = os.environ.get("TOGETHER", "1") == "1"  # adjacent seats only by default
NTFY_TOPIC = "wave_to_earth_notifier"
STATE = Path(__file__).with_name("seen.json")
PAGE_URL = f"https://www.ticketbayglobal.com/en/product/{CATEGORY_ID}"


def fetch_all():
    items, page = [], 0
    while True:
        body = json.dumps({"category_id": CATEGORY_ID, "page": page, "size": 100}).encode()
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)["data"]
        items += data["content"]
        if data.get("last", True):
            return items
        page += 1


def matches(x):
    if x["sale_quantity"] < MIN_QTY:
        return False
    if DATES and not any(x["perform_date"].startswith(d) for d in DATES):
        return False
    if TOGETHER and x.get("is_together") != "YES":
        return False
    return True


def notify(title, msg):
    print(f"{title}\n{msg}")
    # macOS banner + sound
    script = ('on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv)'
              ' sound name "Glass"\nend run')
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", script, msg, title], check=False)
    print(f"Sent to {NTFY_TOPIC}...")
    if NTFY_TOPIC:
        # JSON publish: HTTP headers can't carry Chinese, so the title goes in the body
        body = json.dumps({"topic": NTFY_TOPIC, "title": title, "message": msg,
                           "click": PAGE_URL}, ensure_ascii=False).encode()
        req = urllib.request.Request("https://ntfy.sh/", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
        print(f"Sent to {NTFY_TOPIC}...")


def summarize(items):
    """Per show date: 'N sellers sell K ticket(s)', with adjacent counts."""
    by_date = {}
    for x in items:
        if DATES and not any(x["perform_date"].startswith(d) for d in DATES):
            continue
        q = by_date.setdefault(x["perform_date"][:10], {}).setdefault(x["sale_quantity"], [0, 0])
        q[0] += 1
        q[1] += x.get("is_together") == "YES"
    lines = []
    for date in sorted(by_date):
        parts = []
        for qty in sorted(by_date[date]):
            n, adj = by_date[date][qty]
            s = f"{n} 位賣家各賣 {qty} 張"
            if qty > 1:
                s += f"（{adj} 位為連號座位）"
            parts.append(s)
        lines.append(f"{date}：有" + "，".join(parts))
    return "\n".join(lines) or "目前沒有任何票券。"


def main():
    seen = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    items = fetch_all()
    hits = [x for x in items if matches(x)]
    new = [x for x in hits if str(x["id"]) not in seen]
    kind = "連號" if TOGETHER else ""
    greeting = "哈囉恩恩/老師，"
    if new:
        dates = "、".join(sorted({x["perform_date"][:10] for x in new}))
        headline = (f"好消息！！有 {len(new)} 位賣家賣 {MIN_QTY} 張以上{kind}票券，"
                    f"{dates}這一天的演唱會。")
        notify("🎉 有符合的票券！", f"{greeting}\n{headline}\n{summarize(items)}")
    else:
        headline = f"目前沒有新的 {MIN_QTY} 張以上{kind}票券。"
        notify("票券每小時通知", f"{greeting}\n{headline}\n{summarize(items)}")
    STATE.write_text(json.dumps(sorted(seen | {str(x["id"]) for x in hits})))


if __name__ == "__main__":
    main()
