import urllib.request, json, time
for _ in range(40):
    try:
        urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).read(); break
    except Exception:
        time.sleep(4)
PARA = ("The quick brown fox jumps over the lazy dog while the engine streams tokens from "
        "the pinned host pool; attention sinks stabilise the first layers and the grid "
        "checkpoints every 8192 positions so a diverging prompt can still borrow the head. ")
SA = 'You are a senior infrastructure engineer. ' + PARA * 40
body = {"filename": "94cb49ba171eccea",
        "messages": [
            {"role": "system", "content": SA},
            {"role": "user", "content": PARA * 45 + " (question number 0, please answer briefly)"},
            {"role": "user", "content": "divergent fork question, answer one word"}],
        "chat_template_kwargs": {"enable_thinking": False}}
req = urllib.request.Request('http://127.0.0.1:8090/slots/0?action=restorepp',
                             json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
t0 = time.time()
try:
    r = json.loads(urllib.request.urlopen(req, timeout=180).read())
    print(f"restorepp: {time.time()-t0:.2f}s ->", json.dumps(r, ensure_ascii=False)[:240])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:260])
