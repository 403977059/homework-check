#!/usr/bin/env python3
"""将本地 uploads/ 中的文件迁移到阿里云 OSS，并更新数据库 oss_key"""
import os, sys, sqlite3
import hmac, hashlib, base64
import time, email.utils
from urllib.request import Request, urlopen
from urllib.parse import quote

# === OSS 配置（从环境变量读取，与 app.py 一致）===
OSS_ENDPOINT = os.environ.get("OSS_ENDPOINT")
OSS_BUCKET = os.environ.get("OSS_BUCKET")
OSS_KEY_ID = os.environ.get("OSS_KEY_ID")
OSS_KEY_SECRET = os.environ.get("OSS_KEY_SECRET")

missing = [k for k, v in [("OSS_ENDPOINT", OSS_ENDPOINT), ("OSS_BUCKET", OSS_BUCKET), ("OSS_KEY_ID", OSS_KEY_ID), ("OSS_KEY_SECRET", OSS_KEY_SECRET)] if not v]
if missing:
    print(f"❌ 缺少环境变量: {', '.join(missing)}")
    print("请设置后重试:")
    print('  export OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com')
    print('  export OSS_BUCKET=homework-check')
    print('  export OSS_KEY_ID=xxx')
    print('  export OSS_KEY_SECRET=xxx')
    sys.exit(1)

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "homework.db")
UPLOAD_FOLDER = os.path.join(BASE, "uploads")


def _oss_sign(verb, oss_key):
    resource = f"/{OSS_BUCKET}/{oss_key}"
    s = f"{verb}\n\n\n\n{resource}"
    return base64.b64encode(
        hmac.new(OSS_KEY_SECRET.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()


def upload_file(fpath, okey):
    url = f"https://{OSS_BUCKET}.{OSS_ENDPOINT}/{quote(okey, safe='')}"
    ds = email.utils.formatdate(usegmt=True)
    sig = _oss_sign("PUT", okey)
    hd = {
        "Date": ds,
        "Content-Type": "application/octet-stream",
        "Authorization": f"OSS {OSS_KEY_ID}:{sig}",
    }
    with open(fpath, "rb") as f:
        data = f.read()
    req = Request(url, data=data, headers=hd, method="PUT")
    urlopen(req)
    print(f"  ✅ {okey}")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, date, subject, student, filename, type FROM media "
        "WHERE oss_key IS NULL OR oss_key = ''"
    ).fetchall()

    if not rows:
        print("没有需要迁移的文件（所有记录 oss_key 已存在）")
        return

    total = len(rows)
    ok = 0
    for r in rows:
        fpath = os.path.join(UPLOAD_FOLDER, r["filename"])
        if not os.path.exists(fpath):
            print(f"  ⚠️ 文件不存在: {r['filename']}")
            continue
        okey = f"{r['student']}/{r['date']}/{r['subject']}/{r['filename']}"
        try:
            upload_file(fpath, okey)
            conn.execute("UPDATE media SET oss_key=? WHERE id=?", (okey, r["id"]))
            ok += 1
        except Exception as e:
            print(f"  ❌ {r['filename']}: {e}")

    conn.commit()
    conn.close()
    print(f"\n✅ 完成: {ok}/{total} 条记录迁移成功")


if __name__ == "__main__":
    main()
