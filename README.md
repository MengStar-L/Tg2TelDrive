# Tg2TelDrive

Telegram 频道文件自动同步到 TelDrive —— 实时监听频道新消息，自动注册文件到 TelDrive，并支持删除同步与重复检测。

## 功能特性

- 📁 **实时监听**：自动监听 Telegram 频道新文件，立即注册到 TelDrive
- 🔄 **删除同步**：定时检测 TelDrive 中被删除的文件，自动清理频道对应消息
- 🚫 **重复检测**：检测到频道中新发的文件与 TelDrive 已有文件重名时，自动删除该消息
- 📱 **QR 码登录**：支持扫码登录 Telegram，无需输入手机号

## 部署步骤

### 1. 下载项目

```bash
git clone https://github.com/MengStar-L/Tg2TelDrive.git /opt/Tg2TelDrive
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv /opt/myenv
source /opt/myenv/bin/activate
pip install telethon requests qrcode
```

### 3. 创建配置文件

```bash
cp /opt/Tg2TelDrive/config.example.toml /opt/Tg2TelDrive/config.toml
```

编辑配置文件：

```bash
nano /opt/Tg2TelDrive/config.toml
```

填入你的信息：

```toml
[telegram]
api_id = 12345678                  # 从 https://my.telegram.org 获取
api_hash = "your_api_hash_here"
channel_id = -100xxxxxxxxxx        # Telegram 频道 ID
session_name = "tel2teldrive_session"

[teldrive]
url = "http://your-teldrive-host:7888"
bearer_token = "your_bearer_token_here"
channel_id = xxxxxxxxxx            # 不带 -100 前缀
target_path = "/"
sync_interval = 10                 # 删除同步轮询间隔 (秒)
sync_enabled = true                # 是否开启删除同步
max_scan_messages = 10000          # 启动时扫描历史消息上限
```

> **api_id / api_hash 获取方式**：前往 [my.telegram.org](https://my.telegram.org) → API development tools

### 4. 首次运行（扫码登录）

```bash
cd /opt/Tg2TelDrive
python main.py
```

首次运行时会显示 QR 码，使用手机 Telegram 扫码登录：

> 手机端：设置 → 设备 → 扫描二维码

### 5. 注册为系统服务（开机自启）

创建服务文件：

```bash
cat > /etc/systemd/system/tg2teldrive.service << 'EOF'
[Unit]
Description=Tg2TelDrive Sync Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Tg2TelDrive
ExecStart=/opt/myenv/bin/python /opt/Tg2TelDrive/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

启用并启动服务：

```bash
systemctl daemon-reload
systemctl enable --now tg2teldrive
```

### 6. 确认运行状态

```bash
systemctl status tg2teldrive
```

看到 `active (running)` 即表示部署成功 ✅

## 常用命令

```bash
# 查看实时日志
journalctl -u tg2teldrive -f

# 重启服务
systemctl restart tg2teldrive

# 停止服务
systemctl stop tg2teldrive
```

## License

MIT
