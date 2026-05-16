import base64
import json
from loguru import logger
from common.utils import decrypt


def is_sync_package(data: dict) -> bool:
    try:
        return (
            "body" in data
            and "syncPushPackage" in data["body"]
            and "data" in data["body"]["syncPushPackage"]
            and len(data["body"]["syncPushPackage"]["data"]) > 0
        )
    except Exception:
        return False


def is_chat_message(message: dict) -> bool:
    try:
        return (
            isinstance(message, dict)
            and "1" in message
            and isinstance(message["1"], dict)
            and "10" in message["1"]
            and isinstance(message["1"]["10"], dict)
            and "reminderContent" in message["1"]["10"]
        )
    except Exception:
        return False


def is_typing_status(message: dict) -> bool:
    try:
        return (
            isinstance(message, dict)
            and "1" in message
            and isinstance(message["1"], list)
            and len(message["1"]) > 0
            and isinstance(message["1"][0], dict)
            and "1" in message["1"][0]
            and "@goofish" in message["1"][0].get("1", "")
        )
    except Exception:
        return False


def is_bracket_system_message(text: str) -> bool:
    if not text:
        return False
    clean = text.strip()
    return clean.startswith("[") and clean.endswith("]")


def decrypt_sync_data(sync_data: dict) -> dict | None:
    if "data" not in sync_data:
        logger.debug("sync_data中无data字段")
        return None
    data = sync_data["data"]
    try:
        decoded = base64.b64decode(data).decode("utf-8")
        json.loads(decoded)
        logger.debug("消息为纯文本JSON（系统消息），跳过")
        return None
    except Exception:
        pass
    try:
        decrypted = decrypt(data)
        return json.loads(decrypted)
    except Exception as e:
        logger.error(f"消息解密失败: {e}")
        return None
