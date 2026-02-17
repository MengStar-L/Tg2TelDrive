import asyncio
import base64
import json
import mimetypes
import tomllib
from pathlib import Path

import qrcode
import requests
from telethon import TelegramClient, events
from telethon.tl.functions.auth import (
    ExportLoginTokenRequest,
    ImportLoginTokenRequest,
    AcceptLoginTokenRequest,
)
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    auth,
)

# ================= 加载配置 =================
_CONFIG_PATH = Path(__file__).parent / "config.toml"
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

# 本地映射文件: {file_id: [message_id, ...]}
_MAPPING_PATH = Path(__file__).parent / "file_msg_map.json"
# ============================================


def _load_mapping() -> dict[str, list[int]]:
    """加载本地 file_id → message_ids 映射。"""
    if _MAPPING_PATH.exists():
        try:
            return json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_mapping(mapping: dict[str, list[int]]):
    """保存映射到本地文件。"""
    _MAPPING_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_file_to_teldrive(
    file_name: str,
    file_size: int,
    mime_type: str,
    channel_id: int,
    message_id: int,
) -> str | None:
    """将单个文件信息添加到 TelDrive。成功返回 file_id，失败返回 None。"""
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
        resp = requests.post(
            f"{TELDRIVE_URL}/api/files", headers=headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        file_id = data.get("id", "")

        # 写入本地映射
        if file_id:
            mapping = _load_mapping()
            mapping[file_id] = [message_id]
            _save_mapping(mapping)

        return file_id or None
    except requests.exceptions.HTTPError:
        print(f"  ❌ HTTP 错误: {resp.status_code} - {resp.text}")
        return None
    except Exception as e:
        print(f"  ❌ 未知错误: {e}")
        return None


def extract_file_info(msg) -> dict | None:
    """从 Telethon 的 Message 对象中提取文件元数据。返回 None 表示无文件。"""
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
        largest = max(photo.sizes, key=lambda s: getattr(s, "size", 0), default=None)
        file_size = getattr(largest, "size", 0)
        return {
            "name": f"photo_{msg.id}.jpg",
            "size": file_size,
            "mime_type": "image/jpeg",
        }

    return None


def _list_teldrive_dir(path: str) -> list[dict]:
    """列出 TelDrive 指定目录下的所有条目（单层），返回 item 列表。"""
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    items: list[dict] = []
    page = 1

    while True:
        params = {
            "path": path,
            "op": "list",
            "perPage": 500,
            "page": page,
        }
        try:
            resp = requests.get(
                f"{TELDRIVE_URL}/api/files", headers=headers, params=params
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️ 获取 TelDrive 目录 {path} 失败: {e}")
            return items

        items.extend(data.get("items", []))

        meta = data.get("meta", {})
        total_pages = meta.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1

    return items


def get_teldrive_files() -> dict[str, str]:
    """从 TelDrive 根目录递归获取所有文件。返回 {file_id: file_name}。"""
    result: dict[str, str] = {}
    dirs_to_scan = ["/"]

    while dirs_to_scan:
        current_path = dirs_to_scan.pop()
        items = _list_teldrive_dir(current_path)

        for item in items:
            item_type = item.get("type", "")
            item_id = item.get("id", "")
            item_name = item.get("name", "")

            if item_type == "folder":
                # 拼接子目录路径，继续递归
                sub_path = current_path.rstrip("/") + "/" + item_name
                dirs_to_scan.append(sub_path)
            elif item_id:
                result[item_id] = item_name

    return result


async def build_initial_mapping(client: TelegramClient):
    """启动时扫描频道历史消息，按文件名匹配 TelDrive 文件，补全本地映射。"""
    print("📋 正在构建文件映射...")

    # 获取 TelDrive 当前文件: {file_id: file_name}
    td_files = get_teldrive_files()
    mapping = _load_mapping()
    unmapped_ids = {fid for fid in td_files if fid not in mapping}

    # 清理映射中已不存在于 TelDrive 的旧条目
    stale = [fid for fid in mapping if fid not in td_files]
    if stale:
        for fid in stale:
            mapping.pop(fid)
        _save_mapping(mapping)
        print(f"   清理 {len(stale)} 条过期映射")

    if not unmapped_ids:
        print(f"   映射完整: {len(mapping)} 条记录, 无需扫描频道")
        return

    print(f"   需要匹配 {len(unmapped_ids)} 个文件, 开始扫描频道历史...")

    # 按文件名反查: {name: file_id} (仅未映射的)
    name_to_fid: dict[str, str] = {}
    for fid in unmapped_ids:
        name_to_fid[td_files[fid]] = fid

    # 扫描频道历史消息
    MAX_SCAN = MAX_SCAN_MESSAGES
    found = 0
    scanned = 0

    async for msg in client.iter_messages(CHANNEL_ID, limit=MAX_SCAN):
        scanned += 1

        try:
            file_info = extract_file_info(msg)
        except Exception:
            continue  # 单条消息解析失败不影响整体

        if file_info is None:
            continue

        name = file_info["name"]
        if name in name_to_fid:
            fid = name_to_fid.pop(name)
            mapping[fid] = [msg.id]
            found += 1
            if not name_to_fid:
                break  # 全部找到，提前退出

        # 每 200 条打印进度并保存 (防崩溃丢数据)
        if scanned % 200 == 0:
            _save_mapping(mapping)
            print(f"   ... 已扫描 {scanned} 条消息, 匹配 {found} 个文件")

    _save_mapping(mapping)
    print(f"   扫描完成: 共扫描 {scanned} 条消息, 新建 {found} 条映射, 总计 {len(mapping)} 条记录")
    if name_to_fid:
        print(f"   ⚠️ {len(name_to_fid)} 个 TelDrive 文件未在频道中找到对应消息")


async def sync_deletions(client: TelegramClient):
    """定时对比 TelDrive 文件快照，删除频道中已被 TelDrive 移除的文件消息。"""
    print(f"🔄 删除同步已启动 (每 {SYNC_INTERVAL} 秒检查一次)")

    # CONFIRM_CYCLES 从配置文件读取，默认 3

    prev_files = get_teldrive_files()
    prev_ids = set(prev_files.keys())
    print(f"   初始快照: {len(prev_ids)} 个文件")

    # 待确认删除: {file_id: {"name": str, "msg_ids": list, "count": int}}
    pending_deletions: dict[str, dict] = {}

    while True:
        await asyncio.sleep(SYNC_INTERVAL)

        curr_files = get_teldrive_files()
        curr_ids = set(curr_files.keys())
        curr_names = set(curr_files.values())
        disappeared_ids = prev_ids - curr_ids
        new_ids = curr_ids - prev_ids

        print(f"🔄 同步检查: 上次 {len(prev_ids)} 个 → 本次 {len(curr_ids)} 个"
              f" | 新增 {len(new_ids)} | 消失 {len(disappeared_ids)}")

        mapping = _load_mapping()

        # --- 处理本次消失的文件 ---
        if disappeared_ids:
            for fid in disappeared_ids:
                old_name = prev_files.get(fid, "")
                if old_name and old_name in curr_names:
                    # 文件名仍在，只是 ID 变了（移动/重建）→ 立即迁移映射
                    new_name_to_id = {name: nid for nid, name in curr_files.items()
                                      if nid in new_ids}
                    old_msgs = mapping.pop(fid, [])
                    if old_name in new_name_to_id:
                        new_fid = new_name_to_id[old_name]
                        mapping[new_fid] = old_msgs
                        print(f"  � 映射迁移: {old_name}")
                    _save_mapping(mapping)
                elif fid not in pending_deletions:
                    # 文件名也不在了 → 加入待确认队列
                    pending_deletions[fid] = {
                        "name": old_name,
                        "msg_ids": mapping.get(fid, []),
                        "count": 1,
                    }
                    print(f"  ⏳ 文件 {old_name} 消失，等待确认 (1/{CONFIRM_CYCLES})")

        # --- 检查待确认队列 ---
        confirmed_fids: list[str] = []
        for fid, info in list(pending_deletions.items()):
            name = info["name"]
            # 文件名重新出现了（移动完成） → 取消删除
            if name in curr_names:
                print(f"  ✅ 文件 {name} 已重新出现，取消删除")
                # 迁移映射到新 ID
                for nid, nname in curr_files.items():
                    if nname == name and nid not in mapping:
                        mapping[nid] = info["msg_ids"]
                        print(f"  🔄 映射迁移: {name}")
                        break
                del pending_deletions[fid]
                mapping.pop(fid, None)
                _save_mapping(mapping)
                continue

            # 文件仍然不存在 → 增加计数
            info["count"] += 1
            if info["count"] >= CONFIRM_CYCLES:
                confirmed_fids.append(fid)
            else:
                print(f"  ⏳ 文件 {name} 持续消失 ({info['count']}/{CONFIRM_CYCLES})")

        # --- 执行确认删除 ---
        if confirmed_fids:
            msg_ids_to_delete: list[int] = []
            for fid in confirmed_fids:
                info = pending_deletions.pop(fid)
                msg_ids_to_delete.extend(info["msg_ids"])
                mapping.pop(fid, None)

            if msg_ids_to_delete:
                print(f"🗑️ 确认删除 {len(confirmed_fids)} 个文件 → "
                      f"清理 {len(msg_ids_to_delete)} 条频道消息")
                try:
                    await client.delete_messages(CHANNEL_ID, msg_ids_to_delete)
                    print(f"  ✅ 已删除 {len(msg_ids_to_delete)} 条频道消息")
                except Exception as e:
                    print(f"  ❌ 删除频道消息失败: {e}")
            _save_mapping(mapping)

        # 新增的文件同步到映射
        if new_ids:
            unmapped = [fid for fid in new_ids if fid not in _load_mapping()]
            if unmapped:
                print(f"📋 发现 {len(unmapped)} 个新文件未有映射, 将在下次启动时扫描")

        prev_ids = curr_ids
        prev_files = curr_files


async def qr_login(client: TelegramClient):
    """使用 QR 码扫码登录 Telegram。"""
    print("\n📱 请使用手机 Telegram 扫描以下二维码登录：")
    print("   (手机端: 设置 → 设备 → 扫描二维码)\n")

    while True:
        # 请求登录 token
        result = await client(ExportLoginTokenRequest(
            api_id=API_ID,
            api_hash=API_HASH,
            except_ids=[]
        ))

        if isinstance(result, auth.LoginToken):
            # 生成 QR 码
            token_b64 = base64.urlsafe_b64encode(result.token).decode('utf-8')
            qr_url = f"tg://login?token={token_b64}"

            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr.add_data(qr_url)
            qr.print_ascii(invert=True)

            print(f"\n⏳ 等待扫码... (二维码将在 {result.expires.strftime('%H:%M:%S')} 过期)")

            # 等待扫码，每 3 秒轮询一次
            try:
                while True:
                    await asyncio.sleep(3)
                    try:
                        result = await client(ExportLoginTokenRequest(
                            api_id=API_ID,
                            api_hash=API_HASH,
                            except_ids=[]
                        ))
                        if isinstance(result, auth.LoginTokenSuccess):
                            print("✅ 登录成功！")
                            return
                        elif isinstance(result, auth.LoginTokenMigrateTo):
                            # 需要切换到其他 DC
                            await client._switch_dc(result.dc_id)
                            result = await client(ImportLoginTokenRequest(token=result.token))
                            if isinstance(result, auth.LoginTokenSuccess):
                                print("✅ 登录成功！")
                                return
                    except Exception as e:
                        err_msg = str(e)
                        if "SESSION_PASSWORD_NEEDED" in err_msg:
                            print("\n🔐 此账号启用了两步验证，请输入密码：")
                            from telethon.password import compute_check
                            from telethon.tl.functions.account import GetPasswordRequest
                            password = input("密码: ")
                            pwd = await client(GetPasswordRequest())
                            from telethon.tl.functions.auth import CheckPasswordRequest
                            result = await client(CheckPasswordRequest(
                                password=compute_check(pwd, password)
                            ))
                            print("✅ 登录成功！")
                            return
                        elif "TOKEN_EXPIRED" in err_msg:
                            print("\n⚠️ 二维码已过期，正在刷新...\n")
                            break  # 跳出内层循环，重新生成 QR
                        else:
                            raise
            except KeyboardInterrupt:
                print("\n❌ 用户取消登录。")
                raise

        elif isinstance(result, auth.LoginTokenSuccess):
            print("✅ 登录成功！")
            return

        elif isinstance(result, auth.LoginTokenMigrateTo):
            await client._switch_dc(result.dc_id)
            result = await client(ImportLoginTokenRequest(token=result.token))
            if isinstance(result, auth.LoginTokenSuccess):
                print("✅ 登录成功！")
                return


async def main():
    print("=" * 60)
    print("  Telegram 频道文件 → TelDrive 实时监听服务")
    print("=" * 60)

    # 1. 连接 Telegram
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        await qr_login(client)

    # 2. 构建文件映射 (扫描频道历史 + TelDrive 文件列表)
    await build_initial_mapping(client)

    # 3. 注册新消息事件处理器
    @client.on(events.NewMessage(chats=CHANNEL_ID))
    async def on_new_message(event):
        msg = event.message
        file_info = extract_file_info(msg)
        if file_info is None:
            return

        name = file_info["name"]
        size = file_info["size"]
        print(f"\n📁 检测到新文件: {name} ({size:,} bytes)")

        # 获取本地映射和 TelDrive 文件列表
        mapping = _load_mapping()
        td_files = get_teldrive_files()

        # 1. 本地映射中已有同名文件 → 频道重复消息 → 删除
        mapped_names = set()
        for fid, msg_ids in mapping.items():
            fname = td_files.get(fid, "")
            if fname:
                mapped_names.add(fname)
        if name in mapped_names:
            print(f"  ⚠️ 文件 {name} 已由本程序处理过，自动删除重复消息 (msg_id={msg.id})")
            try:
                await client.delete_messages(CHANNEL_ID, [msg.id])
                print(f"  🗑️ 已删除重复消息 (msg_id={msg.id})")
            except Exception as e:
                print(f"  ❌ 删除重复消息失败: {e}")
            return

        # 2. TelDrive 中已有同名文件但未在本地映射 → TelDrive 已自动导入 → 不添加，仅记录映射
        existing_name_to_fid = {fname: fid for fid, fname in td_files.items()}
        if name in existing_name_to_fid:
            fid = existing_name_to_fid[name]
            mapping[fid] = [msg.id]
            _save_mapping(mapping)
            print(f"  📋 文件 {name} 已存在于 TelDrive (非本程序添加)，仅记录映射")
            return

        # 3. 全新文件 → 添加到 TelDrive
        ok = add_file_to_teldrive(
            file_name=name,
            file_size=size,
            mime_type=file_info["mime_type"],
            channel_id=TELDRIVE_CHANNEL_ID,
            message_id=msg.id,
        )
        if ok:
            print(f"  ✅ 已添加到 TelDrive: {name}")
        else:
            print(f"  ❌ 添加失败: {name}")

    # 4. 启动删除同步后台任务
    if SYNC_ENABLED:
        sync_task = asyncio.create_task(sync_deletions(client))
    else:
        print("\n⏸️ 删除同步已关闭 (sync_enabled = false)")

    # 4. 持续运行
    print(f"\n👂 正在监听频道 {CHANNEL_ID} 的新消息...")
    print("   按 Ctrl+C 停止\n")

    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n👋 监听已停止，断开连接。")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
