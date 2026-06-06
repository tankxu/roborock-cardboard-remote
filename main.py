# ESP32 (MicroPython) 锡纸触摸遥控 -> 直发 miIO -> 石头 T7S
# 方向键按住才动，松手即停；回充键一键回座。
# 手机网页(http://<ip>/) 实时看触摸，并可开关“是否控制扫地机”。
import network, socket, struct, hashlib, json, time, math
import cryptolib
from machine import TouchPad, Pin

# ====== 配置 ======
# 敏感信息从 config.py 读取(已 gitignore, 不上传; 见 config.example.py)
from config import WIFI_SSID, WIFI_PASS, VAC_IP, VAC_DID, VAC_TOKEN
VAC_PORT = 54321
TOKEN    = bytes(bytearray.fromhex(VAC_TOKEN))

# 触摸引脚
PAD_UP    = 4    # T0  前进
PAD_DOWN  = 14   # T6  后退  (原GPIO32是晶振脚弃用)
PAD_LEFT  = 27   # T7  左转
PAD_RIGHT = 13   # T4  右转  (紧挨EN小心)
PAD_HOME  = 0    # T1  回充  (BOOT脚)

SPEED       = 0.29     # m/s  (范围 -0.3~0.3)
TURN_DEG    = 30       # 每次转向角(度)
MOVE_MS     = 1000     # 单次移动指令时长
RESEND_MS   = 300      # 按住时多久重发一次
THRESH_RATIO= 0.75     # 触摸判定默认(网页可调); 电池供电触摸变化小, 需较高
DEBOUNCE    = 3        # 连续N次低于阈值才算真按下(滤噪)
ADAPT       = 0.02     # 未按下时基线向当前读数靠拢的速度(抗温/湿漂移)
CONTROL_DEFAULT = False  # 上电默认: False=仅监视(安全), True=直接当遥控
# ==================

def load_ratio():                       # 开机读上次保存的灵敏度
    try:
        with open("ratio.txt") as f:
            r = float(f.read())
        if 0.4 <= r <= 0.92: return r
    except Exception:
        pass
    return THRESH_RATIO
def save_ratio(r):                      # 写入 flash(松手时调用)
    try:
        with open("ratio.txt", "w") as f:
            f.write("%.2f" % r)
    except Exception:
        pass

KEY = hashlib.md5(TOKEN).digest()
IV  = hashlib.md5(KEY + TOKEN).digest()

def _pad(d):
    n = 16 - (len(d) % 16)
    return d + bytes([n]) * n
def _unpad(d):
    return d[:-d[-1]]
def _encrypt(p):
    return cryptolib.aes(KEY, 2, IV).encrypt(_pad(p))   # 2 = CBC

class MiIO:
    def __init__(self, ip, port):
        self.ip = ip; self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1)
        self.mid = 100
        self.did = None
        self.connect()                 # 失败也不抛, 离线照常运行
    def _hello(self, ip):              # 向某IP握手, did匹配才算扫地机
        try:
            self.sock.sendto(b'\x21\x31\x00\x20' + b'\xff' * 28, (ip, self.port))
            data = self.sock.recv(1024)
            if struct.unpack(">I", data[8:12])[0] != VAC_DID:
                return False
            self.ip = ip; self.did = data[8:12]
            self.stamp = struct.unpack(">I", data[12:16])[0]
            self.t0 = time.time()
            return True
        except Exception:
            return False
    def _scan(self):                   # 扫本机所在网段, 找 did 匹配的设备
        myip = network.WLAN(network.STA_IF).ifconfig()[0]
        pre = myip.rsplit('.', 1)[0]
        ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ss.settimeout(0.05)
        hello = b'\x21\x31\x00\x20' + b'\xff' * 28
        for i in range(1, 255):
            try: ss.sendto(hello, ("%s.%d" % (pre, i), self.port))
            except: pass
        ss.settimeout(2); found = None; t = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t) < 2500:
            try:
                data, addr = ss.recvfrom(1024)
                if len(data) >= 12 and struct.unpack(">I", data[8:12])[0] == VAC_DID:
                    found = addr[0]; break
            except: break
        ss.close(); return found
    def connect(self):
        if self._hello(self.ip):
            print("扫地机 @%s" % self.ip); return True
        print("扫地机不在 %s, 扫描网段..." % self.ip)
        ip = self._scan()
        if ip and self._hello(ip):
            print("自动发现扫地机 @%s" % ip); return True
        self.did = None; print("没找到扫地机, 按键时再试"); return False
    def send(self, method, params):
        if self.did is None and not self.connect():
            return                     # 还连不上就跳过, 不崩
        try:
            self.mid += 1
            cur = self.stamp + (time.time() - self.t0)
            payload = json.dumps({"id": self.mid, "method": method, "params": params}).encode()
            enc  = _encrypt(payload)
            head = struct.pack(">HHI", 0x2131, 32 + len(enc), 0) + self.did + struct.pack(">I", cur)
            chk  = hashlib.md5(head + TOKEN + enc).digest()
            self.sock.sendto(head + chk + enc, (self.ip, self.port))
            self.sock.recv(1024)       # 收掉响应即可
        except Exception:
            self.did = None            # 出错则标记断开, 下次自动重连

def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("连WiFi", WIFI_SSID, "...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(40):
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if not wlan.isconnected():
        raise RuntimeError("WiFi连接失败，检查SSID/密码(必须2.4G)")
    print("WiFi OK", wlan.ifconfig()[0])

# 静态页: 加载一次, JS 每 250ms 拉 /status 局部更新; 顶部开关切换是否控制扫地机
HTML = """<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name=theme-color content="#0a0d12">
<title>T7S 遥控</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{background:#0a0d12}
body{margin:0;min-height:100vh;min-height:100dvh;overscroll-behavior:none;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
 background:#0a0d12;background-image:radial-gradient(1100px 560px at 50% -8%,#1b2433,#0a0d12 62%);
 background-repeat:no-repeat;background-attachment:fixed;color:#e8ecf2;display:flex;justify-content:center;
 padding:calc(24px + env(safe-area-inset-top)) 18px calc(24px + env(safe-area-inset-bottom))}
.wrap{width:100%;max-width:392px}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
.top h1{font-size:21px;font-weight:600;margin:0;letter-spacing:.3px}
.dot{font-size:12.5px;color:#8a93a0;display:flex;align-items:center;gap:7px}
.dot i{width:9px;height:9px;border-radius:50%;background:#3fd07a;box-shadow:0 0 9px #3fd07a;transition:.3s}
.card{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.07);border-radius:20px;
 padding:18px 20px;margin-bottom:16px}
.sw{display:flex;align-items:center;justify-content:space-between;cursor:pointer}
.sw .t{font-size:16px;font-weight:500}.sw .s{font-size:12.5px;color:#8a93a0;margin-top:3px;line-height:1.4}
.tog{position:relative;width:52px;height:31px;border-radius:20px;background:#39414e;transition:.28s;flex:none;margin-left:14px}
.tog::after{content:"";position:absolute;top:3px;left:3px;width:25px;height:25px;border-radius:50%;background:#fff;transition:.28s}
.swcard.on .tog{background:#3fd07a;box-shadow:0 0 18px rgba(63,208,122,.55)}
.swcard.on .tog::after{left:24px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}
.k{position:relative;display:flex;align-items:center;justify-content:center;font-size:30px;border-radius:18px;
 aspect-ratio:1;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);color:#9aa3b1;
 transition:transform .09s,background .12s,box-shadow .12s,color .12s}
.k.e{background:transparent;border:0}
.k.hit{background:linear-gradient(150deg,#5a9dff,#2f6bd6);color:#fff;transform:scale(.93);
 box-shadow:0 0 26px rgba(74,144,255,.6),inset 0 0 0 1px rgba(255,255,255,.25)}
.k.home.hit{background:linear-gradient(150deg,#46d784,#23a85c);box-shadow:0 0 26px rgba(63,208,122,.6)}
.grid.mon{opacity:.55}
.hint{text-align:center;color:#5f6874;font-size:11.5px;margin-top:16px;line-height:1.6}
.dbg{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;color:#566;letter-spacing:.2px}
.tabs{display:flex;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:4px;margin-bottom:16px}
.tab{flex:1;padding:10px;font-size:15px;border:0;background:transparent;color:#8a93a0;border-radius:10px;transition:.2s;font-weight:500}
.tab.act{background:rgba(255,255,255,.12);color:#fff}
.pane{display:none}.pane.act{display:block}
.rc .k{cursor:pointer}
.lead{text-align:center;color:#9aa3b1;font-size:13.5px;margin-bottom:14px}
.cfg{margin-top:14px;text-align:center}
.cfglbl{display:inline-block;color:#5f6874;font-size:12px;cursor:pointer;padding:5px 12px;border-radius:9px;transition:.15s;user-select:none}
.cfglbl:active{background:rgba(255,255,255,.06)}
.cfglbl b{color:#8a93a0;font-weight:600}
.cfgbox{max-height:0;overflow:hidden;transition:max-height .22s ease,padding .22s ease}
.cfgbox.show{max-height:72px;padding:16px 0 12px}
.rng{-webkit-appearance:none;appearance:none;width:82%;height:6px;border-radius:3px;background:rgba(255,255,255,.12);outline:none}
.rng::-webkit-slider-thumb{-webkit-appearance:none;width:20px;height:20px;border-radius:50%;background:#4a90d9;border:2px solid #cfe0fb;box-shadow:0 0 12px rgba(74,144,255,.55);cursor:pointer}
.rng::-moz-range-thumb{width:18px;height:18px;border:2px solid #cfe0fb;border-radius:50%;background:#4a90d9}
</style></head><body><div class=wrap>
<div class=top><h1>T7S 遥控</h1><div class=dot><i id=led></i><span id=st>连接中</span></div></div>
<div class=tabs>
 <button class="tab act" id=tabM onclick="sw('m')">监听</button>
 <button class=tab id=tabR onclick="sw('r')">遥控</button>
</div>
<div class="pane act" id=paneM>
 <div class="card swcard" id=swcard onclick=tog()>
  <div class=sw><div><div class=t>控制扫地机</div><div class=s id=sub>关闭时仅监视触摸，不会移动</div></div><div class=tog></div></div>
 </div>
 <div class=card><div class=grid id=grid>
  <div class="k e"></div><div class=k id=up>↑</div><div class="k e"></div>
  <div class=k id=left>←</div><div class="k home" id=home>⌂</div><div class=k id=right>→</div>
  <div class="k e"></div><div class=k id=down>↓</div><div class="k e"></div>
 </div></div>
 <div class=hint>物理锡纸触摸实时点亮 · 绿色开关控制是否驱动扫地机<br><span class=dbg id=dbg></span></div>
 <div class=cfg>
  <div class=cfglbl onclick=tcfg()>灵敏度 <b id=rtv>0.75</b></div>
  <div class=cfgbox id=cfgbox><input type=range class=rng id=rt min=0.5 max=0.9 step=0.01 value=0.75></div>
 </div>
</div>
<div class=pane id=paneR>
 <div class=lead>按住方向键遥控 · 松手即停 · 中心 ⌂ 回充</div>
 <div class="card rc"><div class=grid>
  <div class="k e"></div><div class=k data-d=up>↑</div><div class="k e"></div>
  <div class=k data-d=left>←</div><div class="k home" data-d=home>⌂</div><div class=k data-d=right>→</div>
  <div class="k e"></div><div class=k data-d=down>↓</div><div class="k e"></div>
 </div></div>
 <div class=hint>此页按下即直接驱动扫地机 · 断连/松手0.7秒内自动停</div>
</div>
<script>
let ctrl=false,inited=false;const ids=['up','down','left','right','home'];
function sw(t){tabM.className='tab'+(t=='m'?' act':'');tabR.className='tab'+(t=='r'?' act':'');
 paneM.className='pane'+(t=='m'?' act':'');paneR.className='pane'+(t=='r'?' act':'');}
async function poll(){try{
 let d=await(await fetch('/status')).json();ctrl=d.ctrl;
 swcard.className='card swcard'+(ctrl?' on':'');
 grid.className='grid'+(ctrl?'':' mon');
 sub.textContent=ctrl?'已开启 · 触摸方向键即可遥控':'关闭时仅监视触摸，不会移动';
 if(d.online){led.style.background='#3fd07a';led.style.boxShadow='0 0 9px #3fd07a';st.textContent='扫地机在线';}
 else{led.style.background='#e0566a';led.style.boxShadow='0 0 9px #e0566a';st.textContent='扫地机离线';}
 let g='';for(const k of ids){let p=d.pads[k];document.getElementById(k).classList.toggle('hit',p.p);g+=k+':'+p.r+' ';}
 dbg.textContent=g;
 if(!inited&&d.ratio){rt.value=d.ratio;rtv.textContent=d.ratio;inited=true;}
}catch(e){}setTimeout(poll,150);}
rt.addEventListener('input',()=>{rtv.textContent=rt.value;clearTimeout(window._rt);window._rt=setTimeout(()=>fetch('/cfg?ratio='+rt.value).catch(()=>{}),100);});
rt.addEventListener('change',()=>{fetch('/cfg?ratio='+rt.value+'&save=1').catch(()=>{});});
async function tog(){try{await fetch('/ctrl?v='+(ctrl?0:1));ctrl=!ctrl;}catch(e){}}
function tcfg(){cfgbox.classList.toggle('show');}
function cmd(d,v){fetch('/cmd?k='+d+'&v='+v).catch(()=>{});}
document.querySelectorAll('.rc .k[data-d]').forEach(btn=>{
 let d=btn.dataset.d,iv=null;
 const go=e=>{e.preventDefault();btn.classList.add('hit');cmd(d,1);if(!iv)iv=setInterval(()=>cmd(d,1),200);};
 const end=e=>{btn.classList.remove('hit');if(iv){clearInterval(iv);iv=null;}cmd(d,0);};
 btn.addEventListener('pointerdown',go);btn.addEventListener('pointerup',end);
 btn.addEventListener('pointerleave',end);btn.addEventListener('pointercancel',end);});
poll();
</script></body></html>"""

def make_pad(gpio):
    tp = TouchPad(Pin(gpio))
    for _ in range(3):            # 预热: 某些脚(GPIO0等)首次read会抛错
        try: tp.read()
        except: pass
        time.sleep_ms(10)
    base = 0; n = 0
    for _ in range(16):
        try:
            base += tp.read(); n += 1
        except:
            pass
        time.sleep_ms(5)
    base = base // n if n else 1000
    return (tp, int(base * THRESH_RATIO), base)

def main():
    wifi_connect()
    print("校准触摸基线(别碰锡纸)...")
    pads = {k: make_pad(g) for k, g in
            (("up",PAD_UP),("down",PAD_DOWN),("left",PAD_LEFT),("right",PAD_RIGHT),("home",PAD_HOME))}
    for k,(tp,th,b0) in pads.items():
        print("  %-5s baseline=%d 阈值=%d" % (k, b0, th))

    vac = MiIO(VAC_IP, VAC_PORT)

    cnt = {k: 0 for k in pads}
    pressed = {k: False for k in pads}
    last_read = {k: 0 for k in pads}
    tpd  = {k: pads[k][0] for k in pads}
    thr  = {k: pads[k][1] for k in pads}
    base = {k: float(pads[k][2]) for k in pads}
    state = {"ctrl": CONTROL_DEFAULT, "ratio": load_ratio()}   # ratio=灵敏度(网页可调, 持久化)
    print("灵敏度(读取保存值): %.2f" % state["ratio"])
    web_until = {"up":0,"down":0,"left":0,"right":0,"home":0}  # 网页遥控: 各键“按住到何时”(死手保护)
    def update_pads():
        for k in pads:
            try:
                v = tpd[k].read()
            except:
                cnt[k] = 0; pressed[k] = False; continue
            last_read[k] = v
            lo = v < thr[k]
            cnt[k] = min(cnt[k] + 1, DEBOUNCE) if lo else 0
            pressed[k] = cnt[k] >= DEBOUNCE
            if not lo:                              # 未按下: 缓慢跟随, 吸收温/湿漂移
                base[k] += (v - base[k]) * ADAPT
                thr[k] = int(base[k] * state["ratio"])

    # --- 手机网页(非阻塞 HTTP): / 静态页, /status JSON, /ctrl?v=0/1 切换控制 ---
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 80)); srv.listen(3); srv.setblocking(False)
    def serve_http():
        try:
            cl, _ = srv.accept()
        except OSError:
            return
        try:
            cl.settimeout(0.6)
            req = b''
            while b'\r\n\r\n' not in req and len(req) < 2048:   # 读干净请求, 避免close发RST
                try: c = cl.recv(512)
                except: break
                if not c: break
                req += c
            if b'/ctrl?v=1' in req: state["ctrl"] = True
            elif b'/ctrl?v=0' in req: state["ctrl"] = False
            if b'/cfg' in req:                       # 灵敏度: /cfg?ratio=0.75
                i = req.find(b'ratio=')
                if i >= 0:
                    num = b''
                    for ch in req[i+6:i+13]:
                        if (48 <= ch <= 57) or ch == 46: num += bytes([ch])
                        else: break
                    try:
                        r = float(num)
                        if 0.4 <= r <= 0.92:
                            state["ratio"] = r
                            if b'save=1' in req: save_ratio(r)   # 松手才写flash
                    except: pass
            if b'/cmd' in req:                       # 网页遥控按键: /cmd?k=<dir>&v=0/1
                nowc = time.ticks_ms()
                for kk in (b'up', b'down', b'left', b'right', b'home'):
                    if b'k=' + kk + b'&v=1' in req:
                        web_until[kk.decode()] = time.ticks_add(nowc, 700)   # 续命0.7s
                    elif b'k=' + kk + b'&v=0' in req:
                        web_until[kk.decode()] = 0
                body = b'ok'; ct = b'text/plain'
            elif (b'/status' in req) or (b'/ctrl' in req) or (b'/cfg' in req):
                d = {"ctrl": state["ctrl"], "online": vac.did is not None, "ratio": state["ratio"],
                     "pads": {k: {"r": last_read[k], "b": int(base[k]), "t": thr[k], "p": pressed[k]} for k in pads}}
                body = json.dumps(d).encode(); ct = b'application/json'
            else:
                body = HTML.encode(); ct = b'text/html; charset=utf-8'
            hdr = b'HTTP/1.0 200 OK\r\nContent-Type:' + ct + b'\r\nContent-Length:' + str(len(body)).encode() + b'\r\nConnection:close\r\n\r\n'
            cl.sendall(hdr + body)
        except Exception:
            pass
        try: cl.close()
        except: pass

    rc_active = False
    home_prev = False
    moving_prev = False
    omega_for = lambda dg: round(math.radians(dg), 1)
    last = time.ticks_ms()
    idle_since = last
    seq = 0
    # 启动安全锁: 等所有键连续稳定松开后再进入控制
    print("等待所有键松开...")
    clear = 0
    while clear < 12:
        update_pads()
        clear = clear + 1 if not any(pressed.values()) else 0
        time.sleep_ms(30)
    for k in cnt: cnt[k] = 0
    ip = network.WLAN(network.STA_IF).ifconfig()[0]
    print("就绪. 手机网页: http://%s/  (控制默认: %s)" % (ip, "开" if CONTROL_DEFAULT else "关/仅监视"))
    while True:
        update_pads()
        serve_http()
        ctrl = state["ctrl"]
        now = time.ticks_ms()
        wu = web_until
        # 有效按键 = (物理触摸 且 监听tab控制开) 或 (网页遥控按键未过期)
        up = (pressed["up"]   and ctrl) or time.ticks_diff(wu["up"],   now) > 0
        dn = (pressed["down"] and ctrl) or time.ticks_diff(wu["down"], now) > 0
        lf = (pressed["left"] and ctrl) or time.ticks_diff(wu["left"], now) > 0
        rt = (pressed["right"]and ctrl) or time.ticks_diff(wu["right"],now) > 0
        hm = (pressed["home"] and ctrl) or time.ticks_diff(wu["home"], now) > 0
        if hm:
            if not home_prev:
                if rc_active:
                    vac.send("app_rc_end", []); rc_active = False
                vac.send("app_charge", [])
                print("-> 回充")
            home_prev = True
            time.sleep_ms(50)
            continue
        home_prev = False
        moving = up or dn or lf or rt
        if moving:
            if not rc_active:
                vac.send("app_rc_start", []); rc_active = True; seq = 0
                time.sleep_ms(200)
            if time.ticks_diff(now, last) > RESEND_MS:
                v = SPEED if up else (-SPEED if dn else 0.0)
                w = omega_for(TURN_DEG) if lf else (omega_for(-TURN_DEG) if rt else 0.0)
                seq += 1
                vac.send("app_rc_move", [{"omega": w, "velocity": v, "duration": MOVE_MS, "seqnum": seq}])
                print("move v=%.2f w=%.1f seq=%d" % (v, w, seq))
                last = now
        else:
            if rc_active:                           # 松手或刚关控制: 停车并退出遥控
                if moving_prev:
                    seq += 1
                    vac.send("app_rc_move", [{"omega":0.0,"velocity":0.0,"duration":500,"seqnum":seq}])
                    idle_since = now
                    print("stop")
                elif time.ticks_diff(now, idle_since) > 8000:
                    vac.send("app_rc_end", []); rc_active = False
                    print("idle -> 退出遥控模式")
        moving_prev = moving
        time.sleep_ms(50)

main()
