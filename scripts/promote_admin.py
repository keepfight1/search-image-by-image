"""Local operator action: grant admin role to an existing account."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    args = parser.parse_args()
    database = Database(Settings.from_env().database_path)
    database.initialize()
    if not database.set_user_role(args.username, "admin"):
        raise SystemExit(f"用户不存在: {args.username}")
    print(f"已授予管理员角色: {args.username}；请重新登录")


if __name__ == "__main__":
    main()
