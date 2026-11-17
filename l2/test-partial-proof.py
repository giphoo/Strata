import urllib.request, json, time

GW = 'http://127.0.0.1:8091'
KEY = 'sk-38-Qwen'


def chat(msgs, tag):
    body = {'model': 'flash', 'messages': msgs, 'max_tokens': 8,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request(GW + '/v1/chat/completions', json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    print(f'[{tag}] {time.time()-t0:.2f}s prompt={r["usage"]["prompt_tokens"]}')
    return (r['choices'][0]['message'].get('content') or '').strip()


def restorepp(filename, msgs):
    body = {"filename": filename, "messages": msgs,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request('http://127.0.0.1:8090/slots/0?action=restorepp',
                                 json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=180).read())
        print(f'restorepp {time.time()-t0:.2f}s:', json.dumps(r, ensure_ascii=False)[:180])
    except urllib.error.HTTPError as e:
        print('HTTP', e.code, e.read().decode()[:200])


PARA = ("Partial restore loads only the leading blocks of each segment while the directory "
        "maps every block offset exactly so a fork borrows just the shared head. ")
S = 'You are the partial-restore prover. ' + PARA * 40

# P2: 三轮, 每轮 ~2.4K
U = [PARA * 45 + f' (turn {i}, answer one word)' for i in range(3)]
m = [{'role': 'system', 'content': S}]
ans = []
for i in range(3):
    m.append({'role': 'user', 'content': U[i]})
    a = chat(m, f'P2-{i+1}')
    ans.append(a)
    m.append({'role': 'assistant', 'content': a})

print('等 68s 让刷新器存档(检查点含轮边界)...')
time.sleep(68)

# 分叉 prompt: 共享前两轮, 第三轮分叉 → 应命中第二轮边界检查点 (~5K)
fork = [{'role': 'system', 'content': S},
        {'role': 'user', 'content': U[0]},
        {'role': 'assistant', 'content': ans[0]},
        {'role': 'user', 'content': U[1]},
        {'role': 'assistant', 'content': ans[1]},
        {'role': 'user', 'content': 'BRANCH question after two shared turns, answer one word'}]

# 找 P2 的链档名
import os
idx = json.load(open('/data/strata/slot-sessions/index.json'))
fam = None
for f, ch in idx.items():
    for k, v in ch.items():
        if v.get('tok', 0) > 6000 and v['ts'] > time.time() - 300:
            fam, chain = f, k
if fam:
    print(f'P2 档: 族={fam[:8]} 链={chain[:8]} tok={idx[fam][chain]["tok"]}')
    restorepp(chain, fork)
else:
    print('未找到 P2 新档, 现有:', {f: [(k[:6], v['tok']) for k, v in ch.items()] for f, ch in idx.items()})
