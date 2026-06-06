# Roborock Cardboard Remote · 石头扫地机纸板遥控器

用一块 **ESP32 + 几片锡纸(铝箔)** 做的石头扫地机实体遥控器：把锡纸贴在纸板上做成方向键，手指触摸即可遥控扫地机；同时内置一个手机网页，可实时监视触摸、切换控制、屏幕遥控。

全程**走局域网 miIO 协议直连扫地机，不经厂商云、不经手机**。ESP32 自己用 MicroPython 实现了 miIO 的握手与 AES 加密。

> A physical remote for Roborock vacuums built from an ESP32 and tin-foil capacitive touch pads. Talks miIO directly over the LAN (no cloud, no phone app), implemented natively in MicroPython.

## 适用范围 / 协议

控制走的是小米 **miIO 本地协议**（UDP 54321 + AES-128-CBC，密钥由设备 token 派生）。这套**对绑定在「米家 / 小米云」上的 Roborock 扫地机是通用的**——不同型号只是 token、DID、model 不同，把它们填进 `config.py` 即可。

- 本项目在 **Roborock T7S（`roborock.vacuum.a14`）** 上验证
- 绑在 **Roborock 自家 App / 云** 上的设备走的是 Roborock 云协议，不适用本项目（用 [python-roborock](https://github.com/Python-roborock/python-roborock)）
- 拿不准就看：你的扫地机是在「米家」里添加的，那就适用

## 硬件

- **ESP32-WROOM-32**（经典款，双核，带电容触摸引脚 T0–T9）。注意 **ESP32-C3/C6 没有电容触摸**，不适用
- 5 片**锡纸/铝箔**（巴掌大小以内），贴在纸板上
- 杜邦线 / 导线若干
- 5V 供电（USB / 充电宝 / 电池模块）

## 接线（触摸引脚）

| 按键 | GPIO | 说明 |
|---|---|---|
| ↑ 前进 | GPIO4 | T0 |
| ↓ 后退 | GPIO14 | T6（注意 GPIO32/33 是 32K 晶振脚，接线后会报错，勿用） |
| ← 左转 | GPIO27 | T7 |
| → 右转 | GPIO13 | T4（紧挨 EN 脚，接线别碰到 EN） |
| ⌂ 回充 | GPIO0 | T1（BOOT 脚；上电瞬间别触摸，否则可能进下载模式） |

接线要点：
- **杜邦线/夹子的金属要直接咬住锡纸金属**，中间不能有胶（胶绝缘，会接不通）
- 锡纸**别压在金属桌面/笔记本外壳上**（接地后触摸会失效报错）
- 用**电池供电时触摸会变弱**（悬空供电缺少接地参考），可在网页里调高「灵敏度」，或在按键背后加一块接 GND 的地参考铝箔

## 刷固件

1. 给 ESP32 烧 [MicroPython](https://micropython.org/download/ESP32_GENERIC/)（本项目用 v1.28.0）：
   ```bash
   pip install esptool mpremote
   esptool --port /dev/cu.usbserial-XXXX erase-flash
   esptool --port /dev/cu.usbserial-XXXX --baud 460800 write-flash -z 0x1000 ESP32_GENERIC-*.bin
   ```
2. 复制配置并填写：
   ```bash
   cp config.example.py config.py   # 然后编辑 config.py 填入 WiFi / token / DID / IP
   ```
3. 上传到设备：
   ```bash
   mpremote connect /dev/cu.usbserial-XXXX cp config.py :config.py
   mpremote connect /dev/cu.usbserial-XXXX cp main.py   :main.py
   ```
   之后 ESP32 一上电就自动运行。

## 如何获取扫地机 token / DID

token 是本地控制的密钥（32 位十六进制），DID 是设备 ID。常见获取方式：

- **[Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)** 或 `miiocli cloud`（python-miio）：用小米账号登录，列出每台设备的 IP / token / DID。注意选对账号**区服**。
- 部分魔改版米家（如 vevs 版）开启日志后会把 token 明文写到外部存储日志里，可用 adb 取出，无需 root。

> ⚠️ token 等同于控制你扫地机的密钥，**切勿公开**。本项目已用 `config.py`（gitignore）隔离。

## 手机网页

ESP32 连上 WiFi 后，手机浏览器打开 `http://<ESP32的IP>/`（同一局域网）：

- **监听 Tab**：实时显示哪片锡纸被摸（发光 D-pad）+ 底部可折叠的「灵敏度」滑条（拖动即调，松手存入 flash，断电也记住）。顶部「控制扫地机」开关决定物理触摸是否真正驱动扫地机（默认关 = 仅监视，方便调试）
- **遥控 Tab**：屏幕上的 D-pad，按住方向键直接遥控扫地机，松手或断连 0.7 秒内自动停（死手保护）

## 主要特性

- MicroPython 原生实现 miIO（握手 + AES-128-CBC + MD5 校验）
- 电容触摸：开机自动校准 + 多采样去抖 + **自适应基线**（抗温/湿漂移）
- 扫地机 **DHCP 换 IP 自动发现**（连不上起始 IP 时按 DID 扫整个网段）
- 扫地机离线不崩溃，恢复后自动重连
- 网页可调灵敏度并持久化到 flash

## 许可证

[MIT](LICENSE)
