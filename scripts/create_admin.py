"""Create a local administrator and save a generated password outside Git."""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.v2 import _hash_password  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="admin")
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    args = parser.parse_args()
    database = Database(args.database)
    database.initialize()
    if database.get_user(args.username):
        raise SystemExit(f"账号已存在，不会覆盖其密码: {args.username}")
    password = secrets.token_urlsafe(24)
    database.create_user(uuid4().hex, args.username, _hash_password(password), datetime.now(timezone.utc).isoformat())
    database.set_user_role(args.username, "admin")
    credentials = args.database.parent / "admin-credentials.txt"
    credentials.write_text(f"用户名: {args.username}\n密码: {password}\n", encoding="utf-8")
    print(f"已创建管理员 {args.username}；登录信息保存在 {credentials}")


if __name__ == "__main__":
    main()
