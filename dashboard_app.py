from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import tomllib
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from io import BytesIO
from itertools import count
from pathlib import Path
from typing import Any

try:
    import psycopg2
except ModuleNotFoundError:
    psycopg2 = None

import qrcode

import qrcode.image.svg
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from telethon import TelegramClient, events
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
from telethon.password import compute_check
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.functions.auth import (
    CheckPasswordRequest,
    ExportLoginTokenRequest,
    ImportLoginTokenRequest,
)
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
    auth,
)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
_CONFIG_PATH = BASE_DIR / "config.toml"
_MAPPING_PATH = BASE_DIR / "file_msg_map.json"

with open(_CONFIG_PATH, "rb") as f:
    _cfg = tomllib.load(f)

API_ID = _cfg["telegram"]["api_id"]
API_HASH = _cfg["telegram"]["api_hash"]
CHANNEL_ID = _cfg["telegram"]["channel_id"]
SESSION_NAME = _cfg["telegram"]["session_name"]

TELDRIVE_URL = _cfg["teldrive"]["url"]
BEARER_TOKEN = _cfg["teldrive"]["bearer_token"]
TELDRIVE_CHANNEL_ID = _cfg["teldrive"]["channel_id"]
SYNC_INTERVAL = _cfg["teldrive"].get("sync_interval", 60)
SYNC_ENABLED = _cfg["teldrive"].get("sync_enabled", True)
MAX_SCAN_MESSAGES = _cfg["teldrive"].get("max_scan_messages", 10000)
CONFIRM_CYCLES = _cfg["teldrive"].get("confirm_cycles", 3)

DB_HOST = _cfg["teldrive"].get("db_host", "")
DB_PORT = _cfg["teldrive"].get("db_port", 5432)
DB_USER = _cfg["teldrive"].get("db_user", "")
DB_PASSWORD = _cfg["teldrive"].get("db_password", "")
DB_NAME = _cfg["teldrive"].get("db_name", "postgres")
DB_CONFIGURED = bool(DB_HOST)
DB_ENABLED = DB_CONFIGURED and psycopg2 is not None


WEB_CFG = _cfg.get("web", {}) if isinstance(_cfg.get("web"), dict) else {}
WEB_HOST = WEB_CFG.get("host", "0.0.0.0")
WEB_PORT = int(WEB_CFG.get("port", 8080))
LOG_BUFFER_SIZE = int(WEB_CFG.get("log_buffer_size", 400))
WEB_LOG_FILE = WEB_CFG.get("log_file", "runtime.log")
LOG_FILE_PATH = Path(WEB_LOG_FILE)
if not LOG_FILE_PATH.is_absolute():
    LOG_FILE_PATH = BASE_DIR / LOG_FILE_PATH

PHASE_LABELS = {
    "starting": "服务启动中",
    "connecting": "连接 Telegram",
    "awaiting_qr": "等待扫码登录",
    "awaiting_password": "等待两步验证",
    "authorized": "登录成功",
    "initializing": "初始化文件映射",
    "running": "实时监听中",
    "reconnecting": "连接中断，准备重连",
    "error": "服务异常",
    "stopped": "服务已停止",
}


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_local_time(value: str | None) -> str:
    if not value:
        return "--"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


class DashboardBroker:
    def __init__(self, log_limit: int):
        now = iso_now()
        self._logs: deque[dict[str, Any]] = deque(maxlen=log_limit)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._state: dict[str, Any] = {
            "phase": "starting",
            "phase_label": PHASE_LABELS["starting"],
            "authorized": False,
            "needs_password": False,
            "qr_image": None,
            "qr_expires_at": None,
            "last_error": None,
            "updated_at": now,
            "service_started_at": now,
            "channel_id": CHANNEL_ID,
            "session_file": f"{SESSION_NAME}.session",
            "sync_enabled": SYNC_ENABLED,
            "sync_interval": SYNC_INTERVAL,
            "confirm_cycles": CONFIRM_CYCLES,
            "max_scan_messages": MAX_SCAN_MESSAGES,
            "log_file": LOG_FILE_PATH.name,
            "log_count": 0,
            "last_log_at": None,
        }

    def snapshot(self) -> dict[str, Any]:
        return dict(self._state)

    def logs_snapshot(self, limit: int = 200) -> list[dict[str, Any]]:
        data = list(self._logs)
        return data[-limit:]

    async def update_state(self, **kwargs: Any):
        if "phase" in kwargs and "phase_label" not in kwargs:
            kwargs["phase_label"] = PHASE_LABELS.get(kwargs["phase"], str(kwargs["phase"]))
        self._state.update(kwargs)
        self._state["updated_at"] = iso_now()
        await self._broadcast({"type": "state", "payload": self.snapshot()})

    def push_log(self, entry: dict[str, Any]):
        self._logs.append(entry)
        self._state["log_count"] = int(self._state.get("log_count", 0)) + 1
        self._state["last_log_at"] = entry["timestamp"]
        self._schedule_broadcast({"type": "log", "payload": entry})

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]):
        self._subscribers.discard(queue)

    def _schedule_broadcast(self, event: dict[str, Any]):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast(event))

    async def _broadcast(self, event: dict[str, Any]):
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    stale.append(queue)
        for queue in stale:
            self._subscribers.discard(queue)


class ActivityLogger:
    def __init__(self, broker: DashboardBroker, log_path: Path):
        self.broker = broker
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._counter = count(1)

    def info(self, message: str):
        self._write("INFO", message)

    def warning(self, message: str):
        self._write("WARN", message)

    def error(self, message: str):
        self._write("ERROR", message)

    def _write(self, level: str, message: str):
        timestamp = iso_now()
        line = f"{format_local_time(timestamp)} [{level}] {message}"
        print(line, flush=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.broker.push_log(
            {
                "id": str(next(self._counter)),
                "timestamp": timestamp,
                "level": level,
                "message": message,
            }
        )


broker = DashboardBroker(LOG_BUFFER_SIZE)
logger = ActivityLogger(broker, LOG_FILE_PATH)


def _load_mapping() -> dict[str, list[int]]:
    if _MAPPING_PATH.exists():
        try:
            return json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_mapping(mapping: dict[str, list[int]]):
    _MAPPING_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_chunk_file(name: str) -> bool:
    return bool(re.search(r"\.\d+$", name))


def _get_base_name(name: str) -> str:
    return re.sub(r"\.\d+$", "", name)


def _is_md5_name(name: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", name))


def build_qr_data_uri(login_url: str) -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=1, box_size=10)
    qr.add_data(login_url)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    svg_bytes = buffer.getvalue()
    encoded = base64.b64encode(svg_bytes).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def add_file_to_teldrive(
    file_name: str,
    file_size: int,
    mime_type: str,
    channel_id: int,
    message_id: int,
) -> str | None:
    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": file_name,
        "type": "file",
        "path": "/",
        "mimeType": mime_type,
        "size": file_size,
        "channelId": channel_id,
        "parts": [{"id": message_id, "salt": ""}],
        "encrypted": False,
    }

    try:
        response = requests.post(f"{TELDRIVE_URL}/api/files", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        file_id = data.get("id", "")
        if file_id:
            mapping = _load_mapping()
            mapping[file_id] = [message_id]
            _save_mapping(mapping)
        return file_id or None
    except requests.exceptions.HTTPError:
        logger.error(f"添加文件到 TelDrive 失败: HTTP {response.status_code} - {response.text}")
        return None
    except Exception as exc:
        logger.error(f"添加文件到 TelDrive 时出现异常: {exc}")
        return None


def extract_file_info(msg: Any) -> dict[str, Any] | None:
    media = msg.media
    if media is None:
        return None

    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc is None:
            return None

        file_name = None
        mime_type = doc.mime_type or "application/octet-stream"
        file_size = doc.size

        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
                break

        if not file_name:
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeVideo):
                    ext = mimetypes.guess_extension(mime_type) or ".mp4"
                    file_name = f"video_{msg.id}{ext}"
                    break
                if isinstance(attr, DocumentAttributeAudio):
                    ext = mimetypes.guess_extension(mime_type) or ".mp3"
                    file_name = f"audio_{msg.id}{ext}"
                    break
            if not file_name:
                ext = mimetypes.guess_extension(mime_type) or ".bin"
                file_name = f"file_{msg.id}{ext}"

        return {
            "name": file_name,
            "size": file_size,
            "mime_type": mime_type,
        }

    if isinstance(media, MessageMediaPhoto):
        photo = media.photo
        if photo is None:
            return None
        largest = max(photo.sizes, key=lambda size: getattr(size, "size", 0), default=None)
        file_size = getattr(largest, "size", 0)
        return {
            "name": f"photo_{msg.id}.jpg",
            "size": file_size,
            "mime_type": "image/jpeg",
        }

    return None


def _list_teldrive_dir(path: str) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    items: list[dict[str, Any]] = []
    page = 1

    while True:
        params = {
            "path": path,
            "op": "list",
            "perPage": 500,
            "page": page,
        }
        try:
            response = requests.get(f"{TELDRIVE_URL}/api/files", headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning(f"获取 TelDrive 目录 {path} 失败: {exc}")
            return items

        items.extend(data.get("items", []))
        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    return items


def get_teldrive_files() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    dirs_to_scan = ["/"]

    while dirs_to_scan:
        current_path = dirs_to_scan.pop()
        items = _list_teldrive_dir(current_path)
        for item in items:
            item_type = item.get("type", "")
            item_id = item.get("id", "")
            item_name = item.get("name", "")
            item_size = item.get("size", 0)
            if item_type == "folder":
                sub_path = current_path.rstrip("/") + "/" + item_name
                dirs_to_scan.append(sub_path)
            elif item_id:
                result[item_id] = {"name": item_name, "size": item_size}

    return result


def _query_db_mapping() -> dict[str, list[int]]:
    if not DB_ENABLED:
        return {}

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
        cur = conn.cursor()
        cur.execute("SELECT id, name, parts FROM teldrive.files WHERE type='file' AND parts IS NOT NULL")
        result: dict[str, list[int]] = {}
        skipped = 0
        for row in cur.fetchall():
            file_id, name, parts = str(row[0]), row[1], row[2]
            if _is_md5_name(name):
                skipped += 1
                continue
            msg_ids = [part["id"] for part in parts if "id" in part]
            if msg_ids:
                result[file_id] = msg_ids
        conn.close()
        if skipped:
            logger.info(f"数据库映射中跳过 {skipped} 个 MD5 分片记录")
        return result
    except Exception as exc:
        logger.warning(f"TelDrive 数据库映射查询失败: {exc}")
        return {}


def _query_db_msg_ids() -> set[int]:
    if not DB_ENABLED:
        return set()

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
        cur = conn.cursor()
        cur.execute("SELECT parts FROM teldrive.files WHERE type='file' AND parts IS NOT NULL")
        all_ids: set[int] = set()
        for (parts,) in cur.fetchall():
            for part in parts:
                if "id" in part:
                    all_ids.add(part["id"])
        conn.close()
        return all_ids
    except Exception as exc:
        logger.warning(f"TelDrive 消息 ID 查询失败: {exc}")
        return set()


async def _find_chunk_messages(client: TelegramClient, base_names: list[str]) -> list[int]:
    chunk_ids: list[int] = []
    base_set = set(base_names)

    async for msg in client.iter_messages(CHANNEL_ID, limit=MAX_SCAN_MESSAGES):
        try:
            file_info = extract_file_info(msg)
        except Exception:
            continue
        if file_info is None:
            continue
        name = file_info["name"]
        if _is_chunk_file(name) and _get_base_name(name) in base_set:
            chunk_ids.append(msg.id)
            logger.info(f"匹配到分片消息: {name} (msg_id={msg.id})")

    return chunk_ids


async def build_initial_mapping(client: TelegramClient):
    logger.info("开始构建文件映射")

    if DB_ENABLED:
        db_mapping = _query_db_mapping()
        if db_mapping:
            _save_mapping(db_mapping)
            logger.info(f"已从数据库构建映射: {len(db_mapping)} 条")
            return
        logger.warning("数据库未返回可用映射，回退到频道扫描")

    td_files = get_teldrive_files()
    mapping = _load_mapping()
    unmapped_ids = {file_id for file_id in td_files if file_id not in mapping}

    stale_ids = [file_id for file_id in mapping if file_id not in td_files]
    if stale_ids:
        for file_id in stale_ids:
            mapping.pop(file_id, None)
        _save_mapping(mapping)
        logger.info(f"已清理 {len(stale_ids)} 条过期映射")

    md5_ids = {file_id for file_id in unmapped_ids if _is_md5_name(td_files[file_id]["name"])}
    if md5_ids:
        logger.info(f"已跳过 {len(md5_ids)} 个 MD5 分片条目")
        unmapped_ids -= md5_ids

    if not unmapped_ids:
        logger.info(f"文件映射已完整，总计 {len(mapping)} 条")
        return

    logger.info(f"待匹配文件 {len(unmapped_ids)} 个，开始扫描频道历史")
    name_to_file_id = {td_files[file_id]["name"]: file_id for file_id in unmapped_ids}
    found = 0
    scanned = 0

    async for msg in client.iter_messages(CHANNEL_ID, limit=MAX_SCAN_MESSAGES):
        scanned += 1
        try:
            file_info = extract_file_info(msg)
        except Exception:
            continue
        if file_info is None:
            continue

        name = file_info["name"]
        if name in name_to_file_id:
            file_id = name_to_file_id.pop(name)
            mapping[file_id] = [msg.id]
            found += 1
            if not name_to_file_id:
                break
        if scanned % 200 == 0:
            _save_mapping(mapping)
            logger.info(f"映射扫描进度: 已扫描 {scanned} 条消息，已匹配 {found} 个文件")

    _save_mapping(mapping)
    logger.info(f"映射扫描完成: 扫描 {scanned} 条消息，新增 {found} 条映射，总计 {len(mapping)} 条")
    if name_to_file_id:
        logger.warning(f"仍有 {len(name_to_file_id)} 个 TelDrive 文件未找到对应消息")


async def sync_deletions(client: TelegramClient):
    logger.info(f"删除同步已启动，轮询间隔 {SYNC_INTERVAL} 秒")
    prev_files = get_teldrive_files()
    prev_ids = set(prev_files.keys())
    logger.info(f"初始 TelDrive 快照共 {len(prev_ids)} 个文件")
    pending_deletions: dict[str, dict[str, Any]] = {}

    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        curr_files = get_teldrive_files()
        curr_ids = set(curr_files.keys())
        curr_names = {info["name"] for info in curr_files.values()}
        disappeared_ids = prev_ids - curr_ids
        new_ids = curr_ids - prev_ids

        logger.info(
            f"同步检查: 上次 {len(prev_ids)} 个 -> 本次 {len(curr_ids)} 个 | 新增 {len(new_ids)} | 消失 {len(disappeared_ids)}"
        )

        mapping = _load_mapping()

        if disappeared_ids:
            for file_id in disappeared_ids:
                old_info = prev_files.get(file_id, {})
                old_name = old_info.get("name", "") if isinstance(old_info, dict) else ""
                if old_name and old_name in curr_names:
                    new_name_to_id = {
                        info["name"]: new_id
                        for new_id, info in curr_files.items()
                        if new_id in new_ids
                    }
                    old_messages = mapping.pop(file_id, [])
                    if old_name in new_name_to_id:
                        new_file_id = new_name_to_id[old_name]
                        mapping[new_file_id] = old_messages
                        logger.info(f"检测到文件迁移，已迁移映射: {old_name}")
                    _save_mapping(mapping)
                elif file_id not in pending_deletions:
                    if _is_md5_name(old_name):
                        continue
                    pending_deletions[file_id] = {
                        "name": old_name,
                        "msg_ids": mapping.get(file_id, []),
                        "count": 1,
                    }
                    logger.warning(f"文件消失待确认: {old_name} (1/{CONFIRM_CYCLES})")

        confirmed_ids: list[str] = []
        for file_id, info in list(pending_deletions.items()):
            name = info["name"]
            if name in curr_names:
                logger.info(f"文件重新出现，取消删除: {name}")
                for new_id, new_info in curr_files.items():
                    if new_info["name"] == name and new_id not in mapping:
                        mapping[new_id] = info["msg_ids"]
                        logger.info(f"已恢复文件映射: {name}")
                        break
                del pending_deletions[file_id]
                mapping.pop(file_id, None)
                _save_mapping(mapping)
                continue

            info["count"] += 1
            if info["count"] >= CONFIRM_CYCLES:
                confirmed_ids.append(file_id)
            else:
                logger.warning(f"文件持续消失: {name} ({info['count']}/{CONFIRM_CYCLES})")

        if confirmed_ids:
            msg_ids_to_delete: list[int] = []
            base_names_to_delete: list[str] = []
            for file_id in confirmed_ids:
                info = pending_deletions.pop(file_id)
                msg_ids_to_delete.extend(info["msg_ids"])
                base_names_to_delete.append(info["name"])
                mapping.pop(file_id, None)

            if base_names_to_delete:
                chunk_msg_ids = await _find_chunk_messages(client, base_names_to_delete)
                if chunk_msg_ids:
                    msg_ids_to_delete.extend(chunk_msg_ids)
                    logger.info(f"额外匹配到 {len(chunk_msg_ids)} 条分片消息，将一起删除")

            if msg_ids_to_delete:
                logger.warning(
                    f"确认删除 {len(confirmed_ids)} 个文件，准备清理 {len(msg_ids_to_delete)} 条频道消息"
                )
                try:
                    await client.delete_messages(CHANNEL_ID, msg_ids_to_delete)
                    logger.info(f"已删除 {len(msg_ids_to_delete)} 条频道消息")
                except Exception as exc:
                    logger.error(f"删除频道消息失败: {exc}")
            _save_mapping(mapping)

        if new_ids:
            mapping = _load_mapping()
            unmapped_ids = [file_id for file_id in new_ids if file_id not in mapping]
            if unmapped_ids and DB_ENABLED:
                db_mapping = _query_db_mapping()
                updated = 0
                for file_id in unmapped_ids:
                    if file_id in db_mapping:
                        mapping[file_id] = db_mapping[file_id]
                        updated += 1
                if updated:
                    _save_mapping(mapping)
                    logger.info(f"已从数据库同步 {updated} 个新增文件映射")
                remaining = len(unmapped_ids) - updated
                if remaining:
                    logger.warning(f"仍有 {remaining} 个新文件暂无数据库记录")
            elif unmapped_ids:
                logger.warning(f"发现 {len(unmapped_ids)} 个新增文件未建立映射 (未配置数据库)")

        prev_ids = curr_ids
        prev_files = curr_files


class Tel2TelDriveService:
    def __init__(self):
        self.client: TelegramClient | None = None
        self.sync_task: asyncio.Task[Any] | None = None
        self.stop_event = asyncio.Event()
        self.refresh_qr_event = asyncio.Event()
        self.password_future: asyncio.Future[str] | None = None

    async def run_forever(self):
        logger.info("=" * 56)
        logger.info("Tel2TelDrive Web 管理服务启动")
        logger.info(f"管理面板地址: http://127.0.0.1:{WEB_PORT}")
        if DB_CONFIGURED and not DB_ENABLED:
            logger.warning("检测到已配置 TelDrive 数据库，但本地未安装 psycopg2-binary，将回退到频道扫描模式")
        logger.info("=" * 56)


        while not self.stop_event.is_set():
            self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
            try:
                await broker.update_state(
                    phase="connecting",
                    authorized=False,
                    needs_password=False,
                    qr_image=None,
                    qr_expires_at=None,
                    last_error=None,
                )
                logger.info("正在连接 Telegram")
                await self.client.connect()

                if not await self.client.is_user_authorized():
                    logger.warning("当前会话未授权，进入扫码登录流程")
                    await self.authorize_with_dashboard(self.client)

                await broker.update_state(
                    phase="initializing",
                    authorized=True,
                    needs_password=False,
                    qr_image=None,
                    qr_expires_at=None,
                    last_error=None,
                )
                await build_initial_mapping(self.client)
                self.register_handlers(self.client)

                if SYNC_ENABLED:
                    self.sync_task = asyncio.create_task(sync_deletions(self.client))
                else:
                    logger.info("删除同步已关闭 (sync_enabled = false)")

                await broker.update_state(
                    phase="running",
                    authorized=True,
                    needs_password=False,
                    qr_image=None,
                    qr_expires_at=None,
                    last_error=None,
                )
                logger.info(f"正在监听频道 {CHANNEL_ID} 的新消息")
                await self.client.run_until_disconnected()
                if self.stop_event.is_set():
                    break
                logger.warning("Telegram 连接已断开")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"服务运行异常: {exc}")
                await broker.update_state(
                    phase="error",
                    authorized=False,
                    needs_password=False,
                    qr_image=None,
                    qr_expires_at=None,
                    last_error=str(exc),
                )
            finally:
                await self._cleanup_client()

            if not self.stop_event.is_set():
                await broker.update_state(
                    phase="reconnecting",
                    authorized=False,
                    needs_password=False,
                    qr_image=None,
                    qr_expires_at=None,
                )
                logger.info("5 秒后尝试重新连接 Telegram")
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

        await broker.update_state(phase="stopped", authorized=False, needs_password=False, qr_image=None)
        logger.info("Tel2TelDrive 服务已停止")

    async def stop(self):
        self.stop_event.set()
        self.refresh_qr_event.set()
        if self.password_future and not self.password_future.done():
            self.password_future.cancel()
        await self._cleanup_client()

    async def request_qr_refresh(self):
        phase = broker.snapshot().get("phase")
        if phase != "awaiting_qr":
            raise RuntimeError("当前不是扫码登录状态，无需刷新二维码")
        self.refresh_qr_event.set()
        logger.info("管理员发起二维码刷新请求")

    async def submit_password(self, password: str):
        if not password:
            raise RuntimeError("两步验证密码不能为空")
        if not self.password_future or self.password_future.done():
            raise RuntimeError("当前无需输入两步验证密码")
        self.password_future.set_result(password)
        logger.info("已收到管理员提交的两步验证密码")

    async def _cleanup_client(self):
        if self.sync_task:
            self.sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.sync_task
            self.sync_task = None

        if self.client:
            with suppress(Exception):
                if self.client.is_connected():
                    await self.client.disconnect()
            self.client = None

    def register_handlers(self, client: TelegramClient):
        @client.on(events.NewMessage(chats=CHANNEL_ID))
        async def on_new_message(event: Any):
            await self.handle_new_message(client, event.message)

    async def handle_new_message(self, client: TelegramClient, msg: Any):
        file_info = extract_file_info(msg)
        if file_info is None:
            return

        name = file_info["name"]
        size = file_info["size"]
        logger.info(f"检测到新文件: {name} ({size:,} bytes)")

        if _is_chunk_file(name):
            logger.info(f"分片文件已跳过: {name} -> {_get_base_name(name)}")
            return

        if _is_md5_name(name):
            logger.info(f"检测到 MD5 分片文件，已跳过: {name}")
            if DB_ENABLED:
                known_ids = _query_db_msg_ids()
                if msg.id in known_ids:
                    logger.info(f"msg_id={msg.id} 已在 TelDrive 数据库中登记")
                else:
                    logger.warning(f"msg_id={msg.id} 尚未在 TelDrive 数据库中找到记录")
            return

        mapping = _load_mapping()
        td_files = get_teldrive_files()

        mapped_names = set()
        for file_id, msg_ids in mapping.items():
            info = td_files.get(file_id)
            file_name = info["name"] if info else ""
            if file_name:
                mapped_names.add(file_name)

        if name in mapped_names:
            logger.warning(f"检测到重复消息，准备删除: {name} (msg_id={msg.id})")
            try:
                await client.delete_messages(CHANNEL_ID, [msg.id])
                logger.info(f"重复消息已删除: {name} (msg_id={msg.id})")
            except Exception as exc:
                logger.error(f"删除重复消息失败: {exc}")
            return

        existing_name_to_id = {info["name"]: file_id for file_id, info in td_files.items()}
        if name in existing_name_to_id:
            file_id = existing_name_to_id[name]
            mapping[file_id] = [msg.id]
            _save_mapping(mapping)
            logger.info(f"TelDrive 已存在该文件，仅补充映射: {name}")
            return

        result = add_file_to_teldrive(
            file_name=name,
            file_size=size,
            mime_type=file_info["mime_type"],
            channel_id=TELDRIVE_CHANNEL_ID,
            message_id=msg.id,
        )
        if result:
            logger.info(f"文件已添加到 TelDrive: {name}")
        else:
            logger.error(f"文件添加失败: {name}")

    async def authorize_with_dashboard(self, client: TelegramClient):
        self.refresh_qr_event.clear()
        await broker.update_state(
            phase="awaiting_qr",
            authorized=False,
            needs_password=False,
            qr_image=None,
            qr_expires_at=None,
            last_error=None,
        )

        while not self.stop_event.is_set():
            result = await client(
                ExportLoginTokenRequest(
                    api_id=API_ID,
                    api_hash=API_HASH,
                    except_ids=[],
                )
            )

            if await self._consume_login_result(client, result):
                return

            if not isinstance(result, auth.LoginToken):
                logger.warning("登录令牌返回异常，正在重试")
                await asyncio.sleep(2)
                continue

            token_b64 = base64.urlsafe_b64encode(result.token).decode("utf-8")
            qr_image = build_qr_data_uri(f"tg://login?token={token_b64}")
            expires_at = result.expires.astimezone().isoformat(timespec="seconds")
            await broker.update_state(
                phase="awaiting_qr",
                authorized=False,
                needs_password=False,
                qr_image=qr_image,
                qr_expires_at=expires_at,
                last_error=None,
            )
            logger.info(f"已生成新的登录二维码，有效期至 {format_local_time(expires_at)}")

            while not self.stop_event.is_set():
                if self.refresh_qr_event.is_set():
                    self.refresh_qr_event.clear()
                    logger.info("二维码已按管理员请求刷新")
                    break

                await asyncio.sleep(3)
                try:
                    poll_result = await client(
                        ExportLoginTokenRequest(
                            api_id=API_ID,
                            api_hash=API_HASH,
                            except_ids=[],
                        )
                    )
                    if await self._consume_login_result(client, poll_result):
                        return
                except SessionPasswordNeededError:
                    await self._complete_password_login(client)
                    return
                except Exception as exc:
                    message = str(exc)
                    if "SESSION_PASSWORD_NEEDED" in message:
                        await self._complete_password_login(client)
                        return
                    if "TOKEN_EXPIRED" in message:
                        logger.warning("登录二维码已过期，正在自动刷新")
                        break
                    raise

    async def _consume_login_result(self, client: TelegramClient, result: Any) -> bool:
        if isinstance(result, auth.LoginTokenSuccess):
            await self._mark_authorized()
            return True
        if isinstance(result, auth.LoginTokenMigrateTo):
            await client._switch_dc(result.dc_id)
            migrated = await client(ImportLoginTokenRequest(token=result.token))
            if isinstance(migrated, auth.LoginTokenSuccess):
                await self._mark_authorized()
                return True
        return False

    async def _mark_authorized(self):
        self.refresh_qr_event.clear()
        if self.password_future and not self.password_future.done():
            self.password_future.cancel()
        self.password_future = None
        await broker.update_state(
            phase="authorized",
            authorized=True,
            needs_password=False,
            qr_image=None,
            qr_expires_at=None,
            last_error=None,
        )
        logger.info("Telegram 登录成功")

    async def _complete_password_login(self, client: TelegramClient):
        await broker.update_state(
            phase="awaiting_password",
            authorized=False,
            needs_password=True,
            qr_image=None,
            qr_expires_at=None,
            last_error=None,
        )
        logger.warning("账号启用了两步验证，请在管理页面输入密码")

        while not self.stop_event.is_set():
            loop = asyncio.get_running_loop()
            self.password_future = loop.create_future()
            try:
                password = await self.password_future
            except asyncio.CancelledError:
                return
            finally:
                self.password_future = None

            try:
                pwd = await client(GetPasswordRequest())
                await client(CheckPasswordRequest(password=compute_check(pwd, password)))
                await self._mark_authorized()
                return
            except PasswordHashInvalidError:
                logger.error("两步验证密码错误，请重新输入")
                await broker.update_state(
                    phase="awaiting_password",
                    authorized=False,
                    needs_password=True,
                    last_error="两步验证密码错误，请重新输入",
                )
            except Exception as exc:
                logger.error(f"两步验证登录失败: {exc}")
                await broker.update_state(
                    phase="awaiting_password",
                    authorized=False,
                    needs_password=True,
                    last_error=str(exc),
                )


service = Tel2TelDriveService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(service.run_forever())
    try:
        yield
    finally:
        await service.stop()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Tel2TelDrive Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/api/bootstrap")
async def bootstrap():
    return {
        "state": broker.snapshot(),
        "logs": broker.logs_snapshot(),
    }


@app.get("/api/stream")
async def stream():
    queue = broker.subscribe()

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/login/refresh")
async def refresh_qr():
    try:
        await service.request_qr_refresh()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/login/password")
async def submit_password(request: Request):
    data = await request.json()
    password = str(data.get("password", ""))
    try:
        await service.submit_password(password)

    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


def run():
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="warning")


if __name__ == "__main__":
    run()
