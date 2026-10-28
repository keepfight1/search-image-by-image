"""Move research sample records from lost reports to found-cat sightings.

The current product flow treats published records as found cats and uses lost-cat
photos only as non-persistent search queries. User-created records are untouched.
The migration is transactional and creates a SQLite backup before changing data.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402


SAMPLE_TYPES = ("cat50_sample", "hellostreetcat_sample")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    args = parser.parse_args()
    database_path = args.database.resolve()

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id FROM lost_pet WHERE source_type IN (?, ?) ORDER BY id", SAMPLE_TYPES
        ).fetchall()
    if not rows:
        print("没有需要迁移的研究样例；数据库已经符合当前单向流程")
        return

    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(database_path) as connection:
        conflicts = connection.execute(
            f"SELECT id FROM sighting WHERE id IN ({placeholders})", ids
        ).fetchall()
    if conflicts:
        raise SystemExit("发现同 ID 的发现线索，已停止迁移以避免覆盖")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(f"app.before-sample-sightings-{stamp}.db")
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO sighting
               (id, species, type, images, description, event_city, event_district, event_time,
                event_lat, event_lng, contact, created_at, owner_user_id, status, source_type, source_cat_id)
               SELECT id, species, 'sighting', images, description, event_city, event_district, event_time,
                      event_lat, event_lng, contact, created_at, owner_user_id, status, source_type, source_cat_id
               FROM lost_pet WHERE source_type IN (?, ?)""",
            SAMPLE_TYPES,
        )
        connection.execute(
            f"UPDATE feature SET record_type = 'sighting' WHERE record_type = 'lost' AND record_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"UPDATE contact_request SET target_type = 'sighting' WHERE target_type = 'lost' AND target_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            f"UPDATE content_report SET target_type = 'sighting' WHERE target_type = 'lost' AND target_id IN ({placeholders})",
            ids,
        )
        connection.execute(
            "DELETE FROM lost_pet WHERE source_type IN (?, ?)", SAMPLE_TYPES
        )
        connection.commit()

    print(f"已将 {len(ids)} 条研究样例迁移为发现线索")
    print(f"迁移前备份：{backup_path}")


if __name__ == "__main__":
    main()
