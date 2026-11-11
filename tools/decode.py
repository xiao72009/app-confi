"""配置内容解码：与应用里 catvod 的 Decoder.verify 规则一致。

支持三种格式：
1. 直接是 JSON；
2. 内容里有 “8 位字母数字 + **” 标记，标记后面是 base64（常见于把配置藏在图片末尾）；
3. 以 “2423” 开头的十六进制 AES-CBC 加密内容。
"""
import base64
import json
import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE64_PREFIX = re.compile(rb"[A-Za-z0-9]{8}\*\*")


def _pad_key(key: str) -> bytes:
    return (key + "0000000000000000"[len(key):]).encode("utf-8")


def _cbc(data: str) -> str:
    raw = bytes.fromhex(data)
    decoded = raw.decode("utf-8", "replace").lower()
    key = _pad_key(decoded[decoded.index("$#") + 2:decoded.index("#$")])
    iv = _pad_key(decoded[-13:])
    body = bytes.fromhex(data[data.index("2324") + 4:len(data) - 26])
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(body) + decryptor.finalize()
    try:
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(plain) + unpadder.finalize()
    except ValueError:
        pass
    return plain.decode("utf-8", "replace")


def _base64_after_marker(data: bytes) -> bytes:
    match = BASE64_PREFIX.search(data)
    if not match or match.end() == len(data):
        return data
    encoded = re.sub(rb"\s+", b"", data[match.end():])
    try:
        return base64.b64decode(encoded + b"=" * (-len(encoded) % 4))
    except ValueError:
        return data


def decode(content: bytes) -> str:
    """把下载到的原始字节解成配置文本；无法识别时原样按 UTF-8 返回。"""
    plain = content.decode("utf-8", "replace").lstrip("﻿")
    if plain.strip().startswith("{") and parse_json(plain) is not None:
        return plain
    if b"**" in content:
        content = _base64_after_marker(content)
    text = content.decode("utf-8", "replace").lstrip("﻿")
    stripped = text.strip()
    if stripped.startswith("2423"):
        try:
            text = _cbc(re.sub(r"\s+", "", stripped))
        except (ValueError, IndexError):
            pass
    return text


def parse_json(text: str):
    """宽松解析：配置里常有注释和多余逗号，先去掉再解析；失败返回 None。"""
    try:
        return json.loads(text)
    except ValueError:
        pass
    cleaned = re.sub(r"(?m)^\s*//.*$", "", text)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except ValueError:
        return None
