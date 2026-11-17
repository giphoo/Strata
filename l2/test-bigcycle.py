import urllib.request, json, time, subprocess, sys

GW = 'http://127.0.0.1:8091'
KEY = 'sk-38-Qwen'
LOG = '/tmp/bigcycle.log'


def log(*a):
    line = ' '.join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def chat(msgs, tag, timeout=900):
    body = {'model': 'flash', 'messages': msgs, 'max_tokens': 8,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request(GW + '/v1/chat/completions', json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        dt = time.time() - t0
        u = r.get('usage', {})
        ans = (r['choices'][0]['message'].get('content') or '').strip()
        log(f'  [{tag}] {dt:.1f}s prompt={u.get("prompt_tokens")} avail_ok ans={ans[:10]!r}')
        return ans
    except Exception as e:
        log(f'  [{tag}] 失败 {time.time()-t0:.1f}s: {str(e)[:90]}')
        return None


PARA = ("The layered cache architecture stores attention keys and values in page-aligned cells "
        "while boundary checkpoints preserve message edges so a diverging conversation can still "
        "borrow the deepest common prefix; the gateway probes before it moves anything and the "
        "engine streams quantized tensors through the pinned host pool at memory bandwidth. ")
S = 'You are assistant X300 for the big-L2-cycle regression. ' + PARA * 30
U = [PARA * 500 + f' (block X300-{i}, answer in one word)' for i in range(12)]

T0 = time.time()
log(f'=== 大会话 L2 全闭环回归 (起点 {time.strftime("%H:%M:%S")}) ===')

# 阶段1: 重建 X (12轮×24K, live 借用应 ~17s/轮)
log('--- 阶段1: 构建 X 332K ---')
hist = [{'role': 'system', 'content': S}]
for i in range(12):
    hist.append({'role': 'user', 'content': U[i]})
    a = chat(hist, f'X-b{i+1}')
    if a is None:
        log('!! 构建中断'); sys.exit(1)
    hist.append({'role': 'assistant', 'content': a})
json.dump(hist, open('/tmp/bigcycle-hist.json', 'w'), ensure_ascii=False)
log(f'X 构建完成, 消息数={len(hist)}, 历史已存 /tmp/bigcycle-hist.json')

# 阶段2: 切离 → bootstrap 落档 (v2.1.5 按本分支祖先链判)
log('--- 阶段2: 切离触发落档 ---')
chat([{'role': 'user', 'content': 'throwaway to trigger the big save, answer ok'}], 'C-切离')

# 阶段3: 灭池重启 (最坏情形: 池全灭, 盘是唯一来源)
log('--- 阶段3: 引擎重启灭池 ---')
subprocess.run(['systemctl', 'restart', 'strata-flash'], check=False)
for _ in range(60):
    time.sleep(5)
    try:
        urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).read()
        log(f'引擎就绪 {time.strftime("%H:%M:%S")}')
        break
    except Exception:
        pass

# 阶段4: 携全史回访 — 自档 restore@restart → 期待 ~6-8s (vs 冷读 ~170s)
log('--- 阶段4: 全史回访 (自档 L2 恢复, 关键测点) ---')
hist2 = json.load(open('/tmp/bigcycle-hist.json'))
hist2.append({'role': 'user', 'content': 'after the full restart, answer one word: are we fast'})
chat(hist2, 'X-回访-自档恢复', timeout=900)
a = json.load(open('/tmp/bigcycle-hist.json'))
hist_full = a + [{'role': 'user', 'content': 'one more turn to confirm pool borrow, answer ok'}]

# 阶段5: 池内二回访 — 期待 ~1-2s
log('--- 阶段5: 池内二回访 ---')
chat(hist_full, 'X-二回访-池借')

log(f'=== 完成, 总耗时 {(time.time()-T0)/60:.1f} 分钟 ===')
