"""Assign non-dialable example contact numbers to research sample reports only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402


def main() -> None:
    database = Database(Settings.from_env().database_path)
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT id, contact FROM lost_pet
               WHERE source_type IN ('cat50_sample', 'hellostreetcat_sample')
               ORDER BY source_type, source_cat_id"""
        ).fetchall()
        used = {row["contact"] for row in connection.execute(
            "SELECT contact FROM lost_pet UNION ALL SELECT contact FROM sighting"
        ) if row["contact"]}
        assigned = 0
        number = 1
        for row in rows:
            if row["contact"]:
                continue
            while True:
                phone = f"000{number:08d}"
                number += 1
                if phone not in used:
                    break
            connection.execute("UPDATE lost_pet SET contact = ? WHERE id = ?", (phone, row["id"]))
            used.add(phone)
            assigned += 1
    print(f"新增 {assigned} 个以 000 开头的演示号码；已有号码未修改")


if __name__ == "__main__":
    main()
