# 复制本文件为 config.py 并填入你自己的值。config.py 已被 .gitignore 排除, 不会上传。
WIFI_SSID = "你的WiFi名称"        # 必须是 2.4GHz 频段, ESP32 不支持 5G
WIFI_PASS = "你的WiFi密码"
VAC_TOKEN = "你的扫地机token"      # 32 位十六进制, 获取方法见 README
VAC_DID   = 0                     # 扫地机设备ID(十进制), 获取方法见 README
VAC_IP    = "192.168.1.100"       # 扫地机局域网IP; 连不上会自动扫整段按 DID 找
