"""Quick RPM probe against the Copilot proxy.

Sends tiny completion requests in rapid succession, measures
when 429s start arriving. Non-destructive — uses max_tokens=5.

Usage: python scripts/probe_rpm.py
"""
import asyncio, time, json, http.client, threading
from concurrent.futures import ThreadPoolExecutor

URL_HOST = "127.0.0.1"
URL_PORT = 8080
URL_PATH = "/v1/chat/completions"
MODEL = "claude-sonnet-4-20250514"
BATCH_SIZE = 10
WAVES = 8
DELAY = 2.0


def send_one(idx):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": 5,
    }).encode()
    t0 = time.monotonic()
    try:
        conn = http.client.HTTPConnection(URL_HOST, URL_PORT, timeout=30)
        conn.request("POST", URL_PATH, body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        status = resp.status
        conn.close()
        return {"idx": idx, "status": status, "ms": (time.monotonic() - t0) * 1000}
    except Exception as e:
        return {"idx": idx, "status": -1, "ms": (time.monotonic() - t0) * 1000, "error": str(e)[:80]}


def main():
    print(f"Probing http://{URL_HOST}:{URL_PORT}{URL_PATH}")
    print(f"Model: {MODEL}")
    print(f"{WAVES} waves x {BATCH_SIZE} = {WAVES * BATCH_SIZE} requests\n")

    all_results = []
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as pool:
        for wave in range(WAVES):
            futures = [pool.submit(send_one, wave * BATCH_SIZE + i) for i in range(BATCH_SIZE)]
            results = [f.result() for f in futures]
            all_results.extend(results)

            ok = sum(1 for r in results if r["status"] == 200)
            limited = sum(1 for r in results if r["status"] == 429)
            errors = sum(1 for r in results if r["status"] not in (200, 429))
            avg_ms = sum(r["ms"] for r in results) / len(results)
            elapsed = time.monotonic() - t_start

            print(f"Wave {wave+1}/{WAVES}: {ok} ok, {limited} 429s, {errors} err | avg {avg_ms:.0f}ms | {elapsed:.1f}s")

            if limited == BATCH_SIZE:
                print("  -> Full wave 429'd -- ceiling found")
                break

            if wave < WAVES - 1:
                time.sleep(DELAY)

    total_time = time.monotonic() - t_start
    total_ok = sum(1 for r in all_results if r["status"] == 200)
    total_429 = sum(1 for r in all_results if r["status"] == 429)
    effective_rpm = total_ok / (total_time / 60) if total_time > 0 else 0

    print(f"\n{'=' * 50}")
    print(f"Total: {len(all_results)} sent, {total_ok} ok, {total_429} rate-limited")
    print(f"Time: {total_time:.1f}s")
    print(f"Effective RPM: {effective_rpm:.0f}")
    first_429 = next((r["idx"] for r in all_results if r["status"] == 429), "never")
    print(f"First 429 at request #{first_429}")


if __name__ == "__main__":
    main()
