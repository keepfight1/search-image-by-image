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
    created_at TEXT NOT NULL,
    owner_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'active'
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
    created_at TEXT NOT NULL,
    owner_user_id TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS feature (
    image_id TEXT PRIMARY KEY,
    image_url TEXT NOT NULL UNIQUE,
    record_type TEXT NOT NULL CHECK (record_type IN ('lost', 'sighting')),
    record_id TEXT NOT NULL,
    feature_path TEXT NOT NULL UNIQUE,
    model_version TEXT NOT NULL DEFAULT 'legacy'
);

CREATE TABLE IF NOT EXISTS app_user (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS app_session (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES app_user(id),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS image_upload (
    image_url TEXT PRIMARY KEY,
    owner_user_id TEXT REFERENCES app_user(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_request (
    id TEXT PRIMARY KEY,
    requester_user_id TEXT NOT NULL REFERENCES app_user(id),
    target_type TEXT NOT NULL CHECK (target_type IN ('lost', 'sighting')),
    target_id TEXT NOT NULL,
    message TEXT NOT NULL,
    reply TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    UNIQUE (requester_user_id, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS content_report (
    id TEXT PRIMARY KEY,
    reporter_user_id TEXT NOT NULL REFERENCES app_user(id),
    target_type TEXT NOT NULL CHECK (target_type IN ('lost', 'sighting')),
    target_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    UNIQUE (reporter_user_id, target_type, target_id)
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
            for table in ("lost_pet", "sighting"):
                columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                if "owner_user_id" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN owner_user_id TEXT")
                if "status" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            feature_columns = {row["name"] for row in connection.execute("PRAGMA table_info(feature)")}
            if "model_version" not in feature_columns:
                connection.execute("ALTER TABLE feature ADD COLUMN model_version TEXT NOT NULL DEFAULT 'legacy'")
            user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(app_user)")}
            if "role" not in user_columns:
                connection.execute("ALTER TABLE app_user ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")

    def insert_publication(self, table: str, record: dict, features: Sequence[dict]) -> None:
        self._validate_table(table)
        with self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {table} (
                    id, species, type, images, description, event_city, event_district,
                    event_time, event_lat, event_lng, contact, created_at, owner_user_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.get("owner_user_id"),
                    record.get("status", "active"),
                ),
            )
            connection.executemany(
                """
                INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path, model_version)
                VALUES (:image_id, :image_url, :record_type, :record_id, :feature_path, :model_version)
                """,
                features,
            )

    def get_publication(self, table: str, record_id: str) -> dict | None:
        self._validate_table(table)
        with self.connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        return self._decode_record(row) if row else None

    def replace_publication(self, table: str, record: dict, owner_id: str, features: Sequence[dict]) -> list[str] | None:
        """Atomically replace editable fields and embeddings; return old feature filenames."""
        self._validate_table(table)
        with self.connect() as connection:
            old = [row["feature_path"] for row in connection.execute(
                "SELECT feature_path FROM feature WHERE record_type = ? AND record_id = ?",
                (record["type"], record["id"]),
            )]
            changed = connection.execute(
                f"""UPDATE {table} SET images = ?, description = ?, event_city = ?, event_district = ?,
                    event_time = ?, event_lat = ?, event_lng = ?
                    WHERE id = ? AND owner_user_id = ? AND status = 'active'""",
                (
                    json.dumps(record["images"], ensure_ascii=False),
                    json.dumps(record["desc"], ensure_ascii=False),
                    record["event_city"], record["event_district"], record["event_time"],
                    record["event_lat"], record["event_lng"], record["id"], owner_id,
                ),
            )
            if changed.rowcount != 1:
                return None
            connection.execute("DELETE FROM feature WHERE record_type = ? AND record_id = ?", (record["type"], record["id"]))
            connection.executemany(
                """INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path, model_version)
                   VALUES (:image_id, :image_url, :record_type, :record_id, :feature_path, :model_version)""",
                features,
            )
        return old

    def image_is_attached(self, image_url: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM feature WHERE image_url = ? LIMIT 1",
                (image_url,),
            ).fetchone()
        return row is not None

    def register_upload(self, image_url: str, owner_user_id: str | None, created_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO image_upload (image_url, owner_user_id, created_at) VALUES (?, ?, ?)",
                (image_url, owner_user_id, created_at),
            )

    def image_owned_by(self, image_url: str, owner_user_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM image_upload WHERE image_url = ? AND owner_user_id = ?",
                (image_url, owner_user_id),
            ).fetchone()
        return row is not None

    def find_candidates(
        self,
        table: str,
        *,
        species: str,
        city: str | None,
        district: str | None = None,
        model_version: str = "legacy",
    ) -> list[dict]:
        self._validate_table(table)
        query = f"""
            SELECT r.*, f.image_id, f.image_url, f.feature_path
            FROM {table} AS r
            INNER JOIN feature AS f ON f.record_id = r.id AND f.record_type = r.type
            WHERE r.species = ? AND r.status = 'active'
              AND f.model_version = ?
        """
        parameters: list[str] = [species, model_version]
        if city:
            query += " AND r.event_city = ?"
            parameters.append(city)
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
            "owner_user_id": row["owner_user_id"],
            "status": row["status"],
        }

    def create_user(self, user_id: str, username: str, password_hash: str, created_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_user (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, created_at),
            )

    def get_user(self, username: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM app_user WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def set_user_role(self, username: str, role: str) -> bool:
        if role not in {"user", "admin"}:
            raise ValueError("非法用户角色")
        with self.connect() as connection:
            changed = connection.execute("UPDATE app_user SET role = ? WHERE username = ?", (role, username))
        return changed.rowcount == 1

    def create_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_session (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, user_id, expires_at),
            )

    def get_session_user(self, token_hash: str, now: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM app_session WHERE token_hash = ? AND expires_at > ?",
                (token_hash, now),
            ).fetchone()
        return row["user_id"] if row else None

    def list_publications(self, table: str, *, owner_id: str | None = None, city: str | None = None, limit: int = 50) -> list[dict]:
        self._validate_table(table)
        conditions = []
        params: list[object] = []
        if owner_id is not None:
            conditions.append("owner_user_id = ?")
            params.append(owner_id)
        else:
            conditions.append("status = 'active'")
        if city:
            conditions.append("event_city = ?")
            params.append(city)
        where = " WHERE " + " AND ".join(conditions)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table}{where} ORDER BY created_at DESC LIMIT ?", (*params, limit)
            ).fetchall()
        return [self._decode_record(row) for row in rows]

    def set_publication_status(self, table: str, record_id: str, owner_id: str, new_status: str) -> bool:
        self._validate_table(table)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET status = ? WHERE id = ? AND owner_user_id = ?",
                (new_status, record_id, owner_id),
            )
        return cursor.rowcount == 1

    def create_contact_request(self, row: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO contact_request (id, requester_user_id, target_type, target_id, message, created_at) "
                "VALUES (:id, :requester_user_id, :target_type, :target_id, :message, :created_at)",
                row,
            )

    def list_contact_requests(self, owner_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT c.* FROM contact_request c
                   LEFT JOIN lost_pet l ON c.target_type = 'lost' AND c.target_id = l.id
                   LEFT JOIN sighting s ON c.target_type = 'sighting' AND c.target_id = s.id
                   WHERE c.requester_user_id = ? OR l.owner_user_id = ? OR s.owner_user_id = ?
                   ORDER BY c.created_at DESC""",
                (owner_id, owner_id, owner_id),
            ).fetchall()
        return [dict(row) | {"direction": "sent" if row["requester_user_id"] == owner_id else "received"} for row in rows]

    def reply_contact_request(self, request_id: str, owner_id: str, reply: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE contact_request SET reply = ?, state = 'replied'
                   WHERE id = ? AND (
                     (target_type = 'lost' AND EXISTS (SELECT 1 FROM lost_pet WHERE id = target_id AND owner_user_id = ?))
                     OR (target_type = 'sighting' AND EXISTS (SELECT 1 FROM sighting WHERE id = target_id AND owner_user_id = ?))
                   )""",
                (reply, request_id, owner_id, owner_id),
            )
        return cursor.rowcount == 1

    def create_content_report(self, row: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO content_report
                   (id, reporter_user_id, target_type, target_id, reason, created_at)
                   VALUES (:id, :reporter_user_id, :target_type, :target_id, :reason, :created_at)""",
                row,
            )

    def list_content_reports(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM content_report ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]

    def moderate_content_report(self, report_id: str, action: str) -> bool:
        if action not in {"hide", "dismiss"}:
            raise ValueError("非法审核动作")
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM content_report WHERE id = ? AND state = 'pending'", (report_id,)).fetchone()
            if not row:
                return False
            connection.execute("UPDATE content_report SET state = ? WHERE id = ?", ("hidden" if action == "hide" else "dismissed", report_id))
            if action == "hide":
                table = "lost_pet" if row["target_type"] == "lost" else "sighting"
                connection.execute(f"UPDATE {table} SET status = 'hidden' WHERE id = ?", (row["target_id"],))
        return True
