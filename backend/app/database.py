from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lost_pet (
    id TEXT PRIMARY KEY,
    species TEXT NOT NULL CHECK (species IN ('cat', 'dog')),
    type TEXT NOT NULL CHECK (type = 'lost'),
    images TEXT NOT NULL,
    description TEXT NOT NULL,
    event_city TEXT NOT NULL,
    event_district TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_lat REAL,
    event_lng REAL,
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sighting (
    id TEXT PRIMARY KEY,
    species TEXT NOT NULL CHECK (species IN ('cat', 'dog')),
    type TEXT NOT NULL CHECK (type = 'sighting'),
    images TEXT NOT NULL,
    description TEXT NOT NULL,
    event_city TEXT NOT NULL,
    event_district TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_lat REAL,
    event_lng REAL,
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature (
    image_id TEXT PRIMARY KEY,
    image_url TEXT NOT NULL UNIQUE,
    record_type TEXT NOT NULL CHECK (record_type IN ('lost', 'sighting')),
    record_id TEXT NOT NULL,
    feature_path TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_lost_pet_region
ON lost_pet (species, event_city, event_district);

CREATE INDEX IF NOT EXISTS idx_sighting_region
ON sighting (species, event_city, event_district);

CREATE INDEX IF NOT EXISTS idx_feature_record
ON feature (record_type, record_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def insert_publication(self, table: str, record: dict, features: Sequence[dict]) -> None:
        self._validate_table(table)
        with self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {table} (
                    id, species, type, images, description, event_city, event_district,
                    event_time, event_lat, event_lng, contact, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["species"],
                    record["type"],
                    json.dumps(record["images"], ensure_ascii=False),
                    json.dumps(record["desc"], ensure_ascii=False),
                    record["event_city"],
                    record["event_district"],
                    record["event_time"],
                    record["event_lat"],
                    record["event_lng"],
                    record["contact"],
                    record["created_at"],
                ),
            )
            connection.executemany(
                """
                INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path)
                VALUES (:image_id, :image_url, :record_type, :record_id, :feature_path)
                """,
                features,
            )

    def get_publication(self, table: str, record_id: str) -> dict | None:
        self._validate_table(table)
        with self.connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        return self._decode_record(row) if row else None

    def image_is_attached(self, image_url: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM feature WHERE image_url = ? LIMIT 1",
                (image_url,),
            ).fetchone()
        return row is not None

    def find_candidates(
        self,
        table: str,
        *,
        species: str,
        city: str,
        district: str | None = None,
    ) -> list[dict]:
        self._validate_table(table)
        query = f"""
            SELECT r.*, f.image_id, f.image_url, f.feature_path
            FROM {table} AS r
            INNER JOIN feature AS f ON f.record_id = r.id AND f.record_type = r.type
            WHERE r.species = ? AND r.event_city = ?
        """
        parameters: list[str] = [species, city]
        if district is not None:
            query += " AND r.event_district = ?"
            parameters.append(district)
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        candidates: list[dict] = []
        for row in rows:
            record = self._decode_record(row)
            record.update(
                image_id=row["image_id"],
                image_url=row["image_url"],
                feature_path=row["feature_path"],
            )
            candidates.append(record)
        return candidates

    @staticmethod
    def _validate_table(table: str) -> None:
        if table not in {"lost_pet", "sighting"}:
            raise ValueError("非法数据表")

    @staticmethod
    def _decode_record(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "species": row["species"],
            "type": row["type"],
            "images": json.loads(row["images"]),
            "desc": json.loads(row["description"]),
            "event_city": row["event_city"],
            "event_district": row["event_district"],
            "event_time": row["event_time"],
            "event_lat": row["event_lat"],
            "event_lng": row["event_lng"],
            "contact": row["contact"],
            "created_at": row["created_at"],
        }
