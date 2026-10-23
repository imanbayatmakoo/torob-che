import asyncio
import json
import sys

from app import agent


async def main(turns):
    s = agent.get_session(None)
    for t in turns:
        print("\n>>> USER:", t if isinstance(t, str) else t)
        evs = []
        if isinstance(t, dict):
            await agent.handle(s, None, t, evs.append)
        else:
            await agent.handle(s, t, None, evs.append)
        for e in evs:
            ty = e["type"]
            if ty == "message":
                print("BOT:", e["text"])
            elif ty == "recommendations":
                print("CARDS:", [(c["role"], c["name"], c["price_from"], c["n_shops"], c["vs_current"]) for c in e["data"]["picks"]], e["data"]["relaxed"])
            elif ty == "shops":
                print("SHOPS:", e["data"]["n"], [(x["shop_name"], x["price"], x["open"]["label"]) for x in e["data"]["shops"][:3]], e["fell_back"])
            elif ty == "contact_result":
                print("CALL:", e["data"]["shop_name"], e["data"]["status"], e["data"]["reply"][:120])
            elif ty == "plan":
                print("PLAN:", [(x["shop_name"], x["confirmed_price"], x["passage"]) for x in e["data"]["stops"]])
            elif ty in ("profile", "current_phone"):
                print(ty.upper() + ":", json.dumps(e.get("profile") or e.get("data"), ensure_ascii=False)[:250])
            elif ty == "chips":
                print("CHIPS:", e["chips"])
    return s


turns = json.loads(sys.argv[1]) if len(sys.argv) > 1 else [
    "سلام، برای مامانم یه گوشی می‌خوام، دوربین خوب و باتری قوی. تا ۷۰ میلیون. الان سامسونگ A10 داره که شارژش زود تموم میشه",
    "قسطی می‌خوام بخرم. فردا ساعت ۵ عصر میرم جمهوری",
]
asyncio.run(main(turns))
