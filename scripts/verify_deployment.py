"""Wait for the checked-out commit to be current on Liara, then check public health."""
import json
import os
import time
import urllib.request


def get_json(url, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
        return json.load(response)


def main():
    token = os.environ["LIARA_API_TOKEN"]
    expected = os.environ["GITHUB_SHA"]
    url = "https://api.iran.liara.ir/v1/projects/torob-che/releases?teamID=6ad86c8384eee4f39401e7b8"
    for _ in range(60):
        try:
            result = get_json(url, token)
            release = next((r for r in result["releases"] if r["_id"] == result.get("currentRelease")), {})
            if release.get("gitInfo", {}).get("commit") == expected and release.get("state") == "READY":
                health = get_json("https://torob-che.liara.run/api/health")
                if health.get("ok") is True:
                    print("Verified current release", expected, "and public health:", health)
                    return
        except Exception as exc:
            print("Verification retry:", type(exc).__name__)
        time.sleep(10)
    raise SystemExit("Expected commit did not become current and healthy within 10 minutes")


if __name__ == "__main__":
    main()
