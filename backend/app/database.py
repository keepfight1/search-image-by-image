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
    status TEXT NOT NULL DEFAULT 'active',
    source_type TEXT NOT NULL DEFAULT 'user',
    source_cat_id TEXT
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
    status TEXT NOT NULL DEFAULT 'active',
    source_type TEXT NOT NULL DEFAULT 'user',
    source_cat_id TEXT
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

CREATE TABLE IF NOT EXISTS cat_identity (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    coat_color TEXT NOT NULL DEFAULT '',
    pattern TEXT NOT NULL DEFAULT '',
    breed TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL,
    image_count INTEGER NOT NULL,
    representative_image_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cat_image (
    image_id TEXT PRIMARY KEY,
    cat_id TEXT NOT NULL REFERENCES cat_identity(id) ON DELETE CASCADE,
    image_path TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    split TEXT NOT NULL,
    model_version TEXT,
    vector BLOB
);

CREATE INDEX IF NOT EXISTS idx_lost_pet_region
ON lost_pet (species, event_city, event_district);

CREATE INDEX IF NOT EXISTS idx_sighting_region
ON sighting (species, event_city, event_district);

CREATE INDEX IF NOT EXISTS idx_feature_record
ON feature (record_type, record_id);

CREATE INDEX IF NOT EXISTS idx_cat_image_cat
ON cat_image (cat_id);
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
                if "source_type" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN source_type TEXT NOT NULL DEFAULT 'user'")
                if "source_cat_id" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN source_cat_id TEXT")
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
                    event_time = ?, event_lat = ?, event_lng = ?, contact = ?
                    WHERE id = ? AND owner_user_id = ? AND status = 'active'""",
                (
                    json.dumps(record["images"], ensure_ascii=False),
                    json.dumps(record["desc"], ensure_ascii=False),
                    record["event_city"], record["event_district"], record["event_time"],
                    record["event_lat"], record["event_lng"], record["contact"], record["id"], owner_id,
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
            "source_type": row["source_type"],
            "source_cat_id": row["source_cat_id"],
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

    def browse_publications(self, record_type: str = "all") -> list[dict]:
        if record_type not in {"all", "lost", "sighting"}:
            raise ValueError("非法记录类型")
        tables = ["lost_pet", "sighting"] if record_type == "all" else ["lost_pet" if record_type == "lost" else "sighting"]
        records: list[dict] = []
        with self.connect() as connection:
            for table in tables:
                rows = connection.execute(f"SELECT * FROM {table} WHERE status = 'active' ORDER BY created_at DESC").fetchall()
                records.extend(self._decode_record(row) for row in rows)
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def admin_list_publications(self) -> list[dict]:
        records: list[dict] = []
        with self.connect() as connection:
            for table in ("lost_pet", "sighting"):
                records.extend(self._decode_record(row) for row in connection.execute(f"SELECT * FROM {table}"))
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def admin_delete_publication(self, table: str, record_id: str) -> bool:
        """Soft delete a report so it disappears from browsing and matching."""
        self._validate_table(table)
        with self.connect() as connection:
            result = connection.execute(
                f"UPDATE {table} SET status = 'deleted' WHERE id = ? AND status != 'deleted'",
                (record_id,),
            )
        return result.rowcount == 1

    def import_cat_dataset(self, identities: Sequence[dict], images: Sequence[dict]) -> None:
        ids = [item["id"] for item in identities]
        if len(ids) != len(set(ids)):
            raise ValueError("猫身份 ID 重复")
        with self.connect() as connection:
            connection.executemany("DELETE FROM cat_identity WHERE id = ?", [(item,) for item in ids])
            connection.executemany(
                """INSERT INTO cat_identity
                   (id, source, coat_color, pattern, breed, review_status, image_count, representative_image_id)
                   VALUES (:id, :source, :coat_color, :pattern, :breed, :review_status, :image_count, :representative_image_id)""",
                identities,
            )
            connection.executemany(
                """INSERT INTO cat_image
                   (image_id, cat_id, image_path, source_file, source_sha256, split, model_version, vector)
                   VALUES (:image_id, :cat_id, :image_path, :source_file, :source_sha256, :split, :model_version, :vector)""",
                images,
            )

    def list_dataset_cats(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM cat_identity ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def get_dataset_cat(self, cat_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cat_identity WHERE id = ?", (cat_id,)).fetchone()
        return dict(row) if row else None

    def get_dataset_image(self, image_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT image_id, cat_id, image_path FROM cat_image WHERE image_id = ?", (image_id,)).fetchone()
        return dict(row) if row else None

    def list_dataset_images(self, cat_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT image_id, image_path, split FROM cat_image WHERE cat_id = ? ORDER BY image_id",
                (cat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_dataset_vectors(self, model_version: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT i.image_id, i.cat_id, i.vector, c.coat_color, c.pattern, c.review_status
                   FROM cat_image i JOIN cat_identity c ON c.id = i.cat_id
                   WHERE i.model_version = ? AND i.vector IS NOT NULL""",
                (model_version,),
            ).fetchall()
        return [dict(row) for row in rows]

    def dataset_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            cats = connection.execute("SELECT COUNT(*) FROM cat_identity").fetchone()[0]
            images = connection.execute("SELECT COUNT(*) FROM cat_image").fetchone()[0]
            vectors = connection.execute("SELECT COUNT(*) FROM cat_image WHERE vector IS NOT NULL").fetchone()[0]
        return {"identity_count": cats, "image_count": images, "vector_count": vectors}

    def feature_counts(self, model_version: str) -> dict[tuple[str, str], int]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT record_type, record_id, COUNT(*) AS image_count
                   FROM feature WHERE model_version = ? GROUP BY record_type, record_id""",
                (model_version,),
            ).fetchall()
        return {(row["record_type"], row["record_id"]): row["image_count"] for row in rows}

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
