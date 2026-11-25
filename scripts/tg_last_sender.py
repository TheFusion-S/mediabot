"""Read a Telegram getUpdates JSON from stdin; print "<id>\t<name>" of the last private-chat sender."""
import json
import sys

data = json.load(sys.stdin)
msgs = [u["message"] for u in data.get("result", [])
        if u.get("message", {}).get("chat", {}).get("type") == "private"]
if msgs:
    frm = msgs[-1]["from"]
    name = frm.get("first_name", "")
    if frm.get("username"):
        name += " @" + frm["username"]
    print(f"{frm['id']}\t{name.strip()}")
