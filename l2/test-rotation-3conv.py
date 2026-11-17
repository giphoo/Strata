#!/usr/bin/env python3
# 三会话轮转全景 v2: X300/Y30/Z400 轮转 + 小借大(同指纹) + 双大会话续聊 + 重启恢复 + 链式小借大
import urllib.request, json, time, os, subprocess

GW=os.environ.get('GW_URL','http://127.0.0.1:8091'); KEY='sk-38-Qwen'
LOG=os.environ.get('ROT_LOG','/tmp/rot300.log')
TAG=os.environ.get('ROT_TAG','')
RESULTS=[]
CURRENT_PHASE='启动前'
def log(*a):
    line=' '.join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG,'a') as f: f.write(line+'\n')

def mem():
    try:
        for l in open('/proc/meminfo'):
            if l.startswith('MemAvailable'): return int(l.split()[1])//1024
    except OSError: return -1

def chat(msgs, tag, timeout=900):
    body={'model':'flash','messages':msgs,'max_tokens':8,'chat_template_kwargs':{'enable_thinking':False}}
    req=urllib.request.Request(GW+'/v1/chat/completions', json.dumps(body).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+KEY})
    t0=time.time()
    try:
        r=json.loads(urllib.request.urlopen(req,timeout=timeout).read())
        dt=time.time()-t0
        u=r.get('usage',{})
        ans=(r['choices'][0]['message'].get('content') or '').strip()
        pt = u.get('prompt_tokens', 0) or 0
        cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0
        ratio = cached / pt if pt > 1000 else 1.0   # 小请求不计
        warn = ' ⚠LOW-REUSE' if ratio < 0.30 and pt > 1000 else ''
        log(f'  [{tag}] {dt:.1f}s prompt={pt} cached={cached} reuse={ratio:.0%} avail={mem()}MB ans={ans[:12]!r}{warn}')
        RESULTS.append({'phase': CURRENT_PHASE, 'tag': tag, 'seconds': dt,
                        'prompt': pt, 'cached': cached, 'reuse': ratio})
        return ans
    except Exception as e:
        log(f'  [{tag}] 失败 {time.time()-t0:.1f}s: {str(e)[:90]} avail={mem()}MB')
        return None

PARA=("The layered cache architecture stores attention keys and values in page-aligned cells "
      "while boundary checkpoints preserve message edges so a diverging conversation can still "
      "borrow the deepest common prefix; the gateway probes before it moves anything and the "
      "engine streams quantized tensors through the pinned host pool at memory bandwidth. ")

def mk_system(name):
    return f'You are assistant {name}{TAG} for the rotation stress test. '+PARA*30

def big(n, seed):
    return PARA*n+f' (block {seed}{TAG}, answer in one word)'

T0=time.time()
def phase(t):
    global CURRENT_PHASE
    CURRENT_PHASE=t
    log(f'=== {t} ({time.strftime("%H:%M:%S")}, 累计{(time.time()-T0)/60:.1f}分) ===')

# ---- 构建: X=12轮×~24K, Y=2轮×~12K, Z=16轮×~24K ----
phase('阶段1 构建')
hist={}
for name, turns, per in [('X240',10,500),('Y30',2,250),('Z240',10,500)]:   # 256K 规格版: 双 240K 大会话
    msgs=[{'role':'system','content':mk_system(name)}]
    hist[name]=msgs
    for i in range(turns):
        msgs.append({'role':'user','content':big(per, f'{name}{i}')})
        a=chat(msgs, f'{name}-b{i+1}')
        if a is None: log(f'!! {name} 中断'); break
        msgs.append({'role':'assistant','content':a})

# 小借大会话 Yx: X 的第1轮头 + 分叉问题 (同指纹: 同system+同U1)
Yx=[hist['X240'][0], hist['X240'][1], hist['X240'][2],
    {'role':'user','content':'small divergent question after the shared head: answer one word'}]

def one_turn(name, k, q=None):
    msgs=hist[name]
    msgs.append({'role':'user','content':q or f'rotation question {k} for {name}: answer one word'})
    a=chat(msgs, f'{name}-r{k}')
    if a is not None: msgs.append({'role':'assistant','content':a})

phase('阶段2 常规轮转×2 (含小借大探针)')
for k in (1,2):
    for name in ('X240','Y30','Z240'):
        one_turn(name,k); time.sleep(18)
    chat(Yx, f'Yx小借大-r{k}')   # 同指纹借用探针: 期待命中第1轮边界检查点 ~26K

phase('阶段3 双大会话续聊 X↔Z ×6 (最小间隔)')
for k in range(6):
    one_turn('X240', 10+k); one_turn('Z240', 10+k)

phase('阶段3.5 重启前 flush (L2 v3: 存档+mini备份+writer清零 — r90 补窗根治)')
flush_t0=time.time()
for _ in range(30):   # 等 writer 队列清零 (异步落盘全落地)
    try:
        d = json.loads(urllib.request.urlopen('http://127.0.0.1:8090/slots', timeout=3).read())
        if d and d[0].get('l2_writer_pending', 0) == 0: break
    except Exception: pass
    time.sleep(2)
time.sleep(12)   # 防抖窗 (8s) 过 → mini 备份到 SSD → 重启后可复活 (组装级恢复)
log(f'flush 完成 (writer清零+mini备份窗口) {time.strftime("%H:%M:%S")} flush_s={time.time()-flush_t0:.1f}')

phase('阶段4 引擎重启 (灭池)')
restart_t0=time.time()
subprocess.run(['systemctl','restart','strata-flash'], check=False)
for _ in range(60):
    time.sleep(5)
    try:
        urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).read()
        log(f'引擎就绪 {time.strftime("%H:%M:%S")} restart_s={time.time()-restart_t0:.1f}'); break
    except Exception: pass

phase('阶段5 恢复轮转 (C路径: 盘→池→借用)')
for name in ('X240','Y30','Z240'):
    one_turn(name, 90); time.sleep(12)
chat(Yx, 'Yx小借大-restart后')   # 链式: X档恢复入池 → Yx 借其头

# ---- L2 2.0 扩展断言: RAM 活层与冷层落位 ----
phase('阶段5.5 二次切换 (停靠池驻留命中 — mib 20480 后应明显快于首轮)')
for k in range(2):
    for name in ('X240','Z240'):
        one_turn(name, 95+k);   # 第二轮起: 驻留换入, 期待秒级而非 160-230s
chat(Yx, 'Yx小借大-驻留后')

phase('阶段6 L2 2.0 活层断言')
HOT='/dev/shm/slot-hot'; COLD='/data/strata/slot-sessions'
try:
    hot=[f for f in os.listdir(HOT) if f.endswith('.state') and not f.startswith('.') and '.l2tmp' not in f]
    cfg=json.load(open('/config/strata/strata-iq4_xs.json'))
    sink_tokens=int(cfg.get('env',{}).get('STRATA_L2_STATE_SINK_TOKENS','262144') or 0)
    log(f'HOT 档数={len(hot)} sink_tokens={sink_tokens}')
    if hot:
        log('OK: saveinc 落 RAM 活层')
    elif sink_tokens == 0:
        log('OK: sink=0，state 对齐写入 L2-2 主档（独立 mini 按配置关闭）')
    else:
        log('!! FAIL: saveinc 未落 RAM 活层')
except OSError as e: log(f'!! HOT_DIR 异常: {e}')

if os.environ.get('EXPECT_V3') == '1':
    try:
        archives=[f for f in os.listdir('/data/Strata-data/slots')
                  if os.path.isfile(os.path.join('/data/Strata-data/slots',f,'manifest'))]
        log(f'V3 archives={len(archives)}')
        if len(archives) < 3:
            log('!! FAIL: expected at least 3 V3 archive directories for fresh X/Y/Z families')
    except OSError as e:
        log(f'!! FAIL: V3 archive scan: {e}')

phase(f'完成 总耗时{(time.time()-T0)/60:.1f}分')

# 请求工作时间与墙钟分离：阶段内的固定sleep不计入request_sum。
log('=== 分阶段请求耗时（不含sleep） ===')
for name in dict.fromkeys(r['phase'] for r in RESULTS):
    vals=sorted(r['seconds'] for r in RESULTS if r['phase']==name)
    if not vals: continue
    p50=vals[len(vals)//2]
    p90=vals[min(len(vals)-1, int(len(vals)*0.9))]
    log(f'  [{name}] n={len(vals)} request_sum={sum(vals):.1f}s p50={p50:.1f}s p90={p90:.1f}s max={max(vals):.1f}s')

# [giphoo] 低复用汇总: 回归日志里 ⚠LOW-REUSE 标记的请求数
try:
    import subprocess as _sp
    out = _sp.check_output(['grep', '-c', 'LOW-REUSE', LOG], text=True).strip()
    n_low = int(out)
    if n_low:
        log(f'!! 低复用警告: {n_low} 条请求复用率<30% (查 restore-feedback.jsonl)')
    else:
        log('OK: 无低复用请求 (全部 ≥30%)')
except Exception:
    pass
