# Tel2TelDrive

将 Telegram 频道中的文件自动同步到 TelDrive，并提供一个可视化 Web 管理面板用于参数配置、扫码登录、查看实时状态和日志。


## 功能特性

- **实时监听频道文件**：检测到 Telegram 频道新文件后，自动注册到 TelDrive
- **删除同步**：定时检查 TelDrive 中已删除的文件，并清理 Telegram 频道中的对应消息
- **重复检测**：当频道中出现与 TelDrive 已有文件重名的消息时，自动删除重复消息
- **Random Chunking 支持**：可选直连 TelDrive PostgreSQL，精确读取 `parts / message_id` 映射，兼容随机分片模式
- **Web 管理面板**：支持直接在网页中配置全部参数，并查看服务状态、登录状态、运行参数和实时日志

- **二维码登录 / 两步验证**：首次登录可通过网页扫码完成；开启两步验证时可在页面直接输入密码
- **自动重连**：Telegram 连接中断后自动尝试恢复

## 运行方式概览

程序入口为 `main.py`：

```python
from dashboard_app import run

if __name__ == "__main__":
    run()
```

启动后会运行一个 FastAPI Web 服务，默认访问地址为：

- `http://127.0.0.1:8080`

页面中可完成以下操作：

- 在网页中填写或修改全部配置参数
- 查看当前运行状态
- 扫码登录 Telegram
- 输入两步验证密码
- 查看实时操作日志
- 查看关键运行参数

## 配置方式说明

- `config.toml` 是**可选项**，不是启动前必须准备的文件
- 即使项目根目录下没有 `config.toml`，程序也可以先启动，并在页面中进入“参数配置”流程
- 所有配置项都可以直接在网页的“参数配置”页面中填写和保存
- 在网页中点击“保存配置”后，程序会自动写入项目根目录下的 `config.toml`
- `config.example.toml` / 手动维护 `config.toml` 仍然支持，但更适合自动化部署、预置参数或无浏览器环境

## 环境要求



- Python 3.10+
- 一个可用的 Telegram API 凭据（`api_id` / `api_hash`）
- 一个可访问的 TelDrive 服务
- 可选：TelDrive PostgreSQL 数据库（用于 Random Chunking 精确映射）

## 安装与启动

### 1. 克隆项目

```bash
git clone https://github.com/MengStar-L/Tg2TelDrive.git
cd Tg2TelDrive
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```


> 如果虚拟环境里没有 `pip`，可以先执行：`python -m ensurepip --upgrade`

### 3. 启动项目

```bash
source .venv/bin/activate
python main.py
```

启动成功后，打开浏览器访问：


- `http://127.0.0.1:8080`

如果当前还没有 `config.toml`，服务会显示“等待网页配置”，这是正常现象。

### 4. 在网页中配置（推荐）

这是默认推荐方式，也是最简单的方式：

- **不需要预先创建 `config.toml`**
- 打开网页中的“参数配置”页面
- 填写 Telegram、TelDrive、Web 面板相关参数
- 点击“保存配置”后，程序会自动生成或更新项目根目录下的 `config.toml`
- Telegram / TelDrive 配置保存后会自动重载
- 如果修改了 `web.host`、`web.port` 或 `web.log_buffer_size`，需要重启进程后完全生效

配置完成后，可直接在 Web 管理面板中使用手机 Telegram 扫码登录：

- 手机 Telegram → `设置` → `设备` → `连接桌面设备` / 扫码

### 5. 手动编辑配置文件（可选）

如果你更习惯文件方式，或需要在部署前预置参数，也可以手动创建并编辑 `config.toml`。

```bash
cp config.example.toml config.toml
```


请根据你的环境修改 `config.toml`：

```toml
[telegram]
api_id = 12345678
api_hash = "your_api_hash_here"
channel_id = -100xxxxxxxxxx
session_name = "tel2teldrive_session"

[teldrive]
url = "http://your-teldrive-host:7888"
bearer_token = "your_bearer_token_here"
channel_id = xxxxxxxxxx
sync_interval = 10
sync_enabled = true
max_scan_messages = 10000
confirm_cycles = 3

# 可选：用于 Random Chunking 精确映射
# db_host = "your-db-host"
# db_port = 5432
# db_user = "teldrive"
# db_password = "your_password"
# db_name = "postgres"

[web]
host = "0.0.0.0"
port = 8080
log_buffer_size = 400
log_file = "runtime.log"
```


## 配置项说明

以下配置项既可以通过网页“参数配置”页面设置，也可以通过手动编辑 `config.toml` 维护。

### `[telegram]`


- `api_id`：Telegram API ID
- `api_hash`：Telegram API Hash
- `channel_id`：需要监听的 Telegram 频道 ID
- `session_name`：本地会话文件名，不需要带 `.session`

### `[teldrive]`

- `url`：TelDrive 后端地址
- `bearer_token`：TelDrive 的 Bearer Token
- `channel_id`：TelDrive 注册文件时使用的频道 ID，**不带** `-100`
- `sync_interval`：删除同步轮询间隔（秒）
- `sync_enabled`：是否启用删除同步
- `max_scan_messages`：启动时扫描频道历史消息的最大数量
- `confirm_cycles`：文件消失后确认删除所需的连续检查次数
- `db_*`：可选数据库连接配置，仅在需要 Random Chunking 精确映射时使用

### `[web]`

- `host`：Web 管理面板监听地址
- `port`：Web 管理面板端口
- `log_buffer_size`：页面中保留的最近日志条数
- `log_file`：落盘日志文件名

## 使用 systemd 部署（Linux）

将项目作为系统服务运行：

```bash
sudo cp tg2teldrive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tg2teldrive
```

查看状态：

```bash
sudo systemctl status tg2teldrive
```

查看日志：

```bash
journalctl -u tg2teldrive -f
```

## 项目更新方法

下面是推荐的更新步骤。**更新后建议重新安装依赖，并检查 `config.example.toml` 是否新增配置项。**

### Linux

```bash
cd /opt/Tg2TelDrive
git pull origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```


### Linux systemd 服务更新

如果你是用 `systemd` 运行，更新命令建议使用：

```bash
cd /opt/Tg2TelDrive
git pull origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl restart tg2teldrive
sudo systemctl status tg2teldrive
```

### 更新时检查配置差异

每次更新后，建议对比：

- `config.example.toml`
- `config.toml`

如果示例配置新增了字段，请手动同步到你的 `config.toml`。

## 常用命令

### 本地运行

```bash
source .venv/bin/activate
python main.py
```


### 服务管理（Linux）

```bash
sudo systemctl restart tg2teldrive
sudo systemctl stop tg2teldrive
sudo systemctl start tg2teldrive
sudo systemctl status tg2teldrive
journalctl -u tg2teldrive -f
```

## 常见问题

### 1. `ModuleNotFoundError: No module named 'qrcode'`

说明当前虚拟环境依赖未安装完整，执行：

```bash
python -m pip install -r requirements.txt
```

### 2. 页面能打开，但没有二维码

请检查：

- 是否已经在网页“参数配置”页面完成 Telegram / TelDrive 必填项，或已正确填写 `config.toml`
- 当前网络是否可以正常连接 Telegram
- 日志面板中是否有异常信息


### 3. 删除同步不生效

请检查：

- `sync_enabled = true`
- `sync_interval` 是否设置合理
- TelDrive API 与频道映射是否正常

## License

MIT

