#!/usr/bin/env python3
# 小借大全景实验: A(大会话,~17K) 存档 → C(触发切换存档) → probe B1/B2 → 实发 B1
import urllib.request, json, time, sys

GW = 'http://127.0.0.1:8091'
KEY = 'sk-38-Qwen'

def call(path, body, timeout=180):
    req = urllib.request.Request(GW + path, json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return r, time.time() - t0

def chat(msgs, tools, max_tokens=12, tag=''):
    body = {'model': 'flash', 'messages': msgs, 'tools': tools, 'max_tokens': max_tokens,
            'chat_template_kwargs': {'enable_thinking': False}}
    r, dt = call('/v1/chat/completions', body)
    u = r.get('usage', {})
    print(f"  [{tag}] {dt:.2f}s ttft_usage: prompt={u.get('prompt_tokens')} total={u.get('total_tokens')}", flush=True)
    return r

def probe(msgs, tools, tag):
    body = {'model': 'flash', 'messages': msgs, 'tools': tools,
            'chat_template_kwargs': {'enable_thinking': False}}
    try:
        r, dt = call('/v1/cache/probe', body, timeout=60)
        print(f"  [probe {tag}] {dt*1000:.0f}ms -> {json.dumps(r, ensure_ascii=False)[:220]}", flush=True)
        return r
    except Exception as e:
        print(f"  [probe {tag}] 失败: {e}", flush=True)

PARA = ("The quick brown fox jumps over the lazy dog while the engine streams tokens from "
        "the pinned host pool; attention sinks stabilise the first layers and the grid "
        "checkpoints every 8192 positions so a diverging prompt can still borrow the head. ")

def big_text(k):
    return PARA * k   # ~48 token/次

TOOLS = [{'type': 'function', 'function': {'name': 'ping', 'description': 'test tool',
          'parameters': {'type': 'object', 'properties': {'x': {'type': 'string'}}}}}]

SYSTEM_A = 'You are a senior infrastructure engineer. ' + big_text(40)   # ~2.2K tok
U = [big_text(45) + f' (question number {i}, please answer briefly)' for i in range(6)]  # 每个 ~2.4K tok

# A: 6 轮, 每轮全历史重发
print('=== A 大会话构建 (system~2.2K + 6×U~2.4K) ===', flush=True)
msgs = [{'role': 'system', 'content': SYSTEM_A}]
for i in range(6):
    msgs = msgs + [{'role': 'user', 'content': U[i]},
                   {'role': 'assistant', 'content': 'ok'}] if i else \
          [msgs[0], {'role': 'user', 'content': U[0]},
           {'role': 'assistant', 'content': 'ok'}]
    # 重建: msgs = system + (u,a)*i+1
    msgs = [{'role': 'system', 'content': SYSTEM_A}]
    for j in range(i + 1):
        msgs.append({'role': 'user', 'content': U[j]})
        msgs.append({'role': 'assistant', 'content': 'ok'})
    chat(msgs, TOOLS, tag=f'A{i+1}')

print('=== C 触发切换 → A 应被 bootstrap 存档 ===', flush=True)
chat([{'role': 'user', 'content': 'unrelated throwaway question, answer ok'}], TOOLS, tag='C')

time.sleep(8)   # 等存档落盘

# B1: 同指纹 (同 system+tools+U1 完整), 分叉: 直接问新问题 (跳过 A 的后续轮)
B1 = [{'role': 'system', 'content': SYSTEM_A},
      {'role': 'user', 'content': U[0]},
      {'role': 'user', 'content': 'NEW QUESTION: what is the cache borrow length? answer in one word'}]
print('=== probe B1 (同指纹深借, 期待命中 turn1 边界检查点 ~4.7K) ===', flush=True)
probe(B1, TOOLS, 'B1')
print('=== 实发 B1 ===', flush=True)
chat(B1, TOOLS, tag='B1-real')

# B2: 异指纹 (system 尾加一句), 浅借极限
SYSTEM_B2 = SYSTEM_A + ' One more sentence changes the fingerprint.'
B2 = [{'role': 'system', 'content': SYSTEM_B2},
      {'role': 'user', 'content': 'short question, answer ok'}]
print('=== probe B2 (异指纹, 共同前缀=tools+systemA ~2.3K, 低于最早检查点?) ===', flush=True)
probe(B2, TOOLS, 'B2')

print('=== 完成, 查看日志 ===', flush=True)
