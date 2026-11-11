"""给 manifest/sources.json 签名，生成 manifest/sources.json.sig（SHA256withECDSA，DER 签名的 base64）。

私钥从环境变量 MANIFEST_SIGNING_KEY（PEM 全文，GitHub Actions 里来自仓库密钥）读取，
本地也可以用 --key 私钥文件路径。
已有签名仍然有效（清单没变）时不重新签名：ECDSA 每次签出来的结果都不同，重签会产生无意义的提交。

用法：python tools/sign_manifest.py [--key 私钥文件]
"""
import base64
import os
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "manifest", "sources.json")
SIG = MANIFEST + ".sig"


def load_key():
    if "--key" in sys.argv:
        with open(sys.argv[sys.argv.index("--key") + 1], "rb") as f:
            pem = f.read()
    else:
        pem = os.environ.get("MANIFEST_SIGNING_KEY", "").encode()
    if not pem.strip():
        sys.exit("没有私钥：请设置环境变量 MANIFEST_SIGNING_KEY 或用 --key 指定私钥文件")
    return serialization.load_pem_private_key(pem, password=None)


def main():
    key = load_key()
    with open(MANIFEST, "rb") as f:
        data = f.read()
    if os.path.isfile(SIG):
        with open(SIG, encoding="ascii") as f:
            old = base64.b64decode(f.read().strip())
        try:
            key.public_key().verify(old, data, ec.ECDSA(hashes.SHA256()))
            print("签名仍然有效，不重新签名")
            return
        except InvalidSignature:
            pass
    signature = key.sign(data, ec.ECDSA(hashes.SHA256()))
    with open(SIG, "w", encoding="ascii", newline="\n") as f:
        f.write(base64.b64encode(signature).decode() + "\n")
    print("已签名：" + SIG)


if __name__ == "__main__":
    main()
