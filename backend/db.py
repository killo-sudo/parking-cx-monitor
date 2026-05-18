#!/usr/bin/env python3
"""SQLite 래퍼 — 라이브러리로 import하거나 CLI로 직접 실행 가능."""

import sqlite3
import json
import sys
import os
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

if getattr(sys, 'frozen', False):
    ROOT_DIR     = Path(sys.executable).parent.parent
    WRITABLE_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'parking-cx-monitor'
else:
    ROOT_DIR     = Path(__file__).parent.parent
    WRITABLE_DIR = ROOT_DIR

DATA_DIR = ROOT_DIR / "data"
WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH  = WRITABLE_DIR / "monitor.db"


def get_conn() -> sqlite3.Connection:
    WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """테이블 생성 (없으면) + 스키마 마이그레이션."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS services (
                id        TEXT PRIMARY KEY,
                name_ko   TEXT,
                operator  TEXT,
                category  TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS changes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id   TEXT NOT NULL,
                published_at DATE NOT NULL,
                source_type  TEXT,
                change_type  TEXT,
                title        TEXT,
                summary      TEXT,
                url          TEXT,
                url_hash     TEXT UNIQUE,
                sentiment    TEXT DEFAULT 'neutral',
                collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES services(id)
            );

            CREATE INDEX IF NOT EXISTS idx_changes_published
                ON changes(published_at);
            CREATE INDEX IF NOT EXISTS idx_changes_service
                ON changes(service_id);
            CREATE INDEX IF NOT EXISTS idx_changes_collected
                ON changes(collected_at);

            CREATE TABLE IF NOT EXISTS html_snapshots (
                service_id   TEXT,
                url          TEXT,
                content_hash TEXT,
                content_text TEXT,
                snapshot_at  DATETIME,
                PRIMARY KEY (service_id, url)
            );

            CREATE TABLE IF NOT EXISTS app_info (
                service_id   TEXT,
                platform     TEXT,
                app_id       TEXT,
                rating       REAL,
                num_ratings  INTEGER,
                version      TEXT,
                update_notes TEXT,
                checked_at   DATETIME,
                PRIMARY KEY (service_id, platform)
            );

            CREATE TABLE IF NOT EXISTS collection_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                status        TEXT,
                items_added   INTEGER DEFAULT 0,
                items_removed INTEGER DEFAULT 0,
                notes         TEXT
            );

            CREATE TABLE IF NOT EXISTS app_info_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id   TEXT,
                platform     TEXT,
                rating       REAL,
                num_ratings  INTEGER,
                version      TEXT,
                recorded_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_aih_svc_plat
                ON app_info_history(service_id, platform, recorded_at);
        """)

    # 기존 DB 마이그레이션 (컬럼 추가)
    with get_conn() as conn:
        for sql in [
            "ALTER TABLE html_snapshots ADD COLUMN content_text TEXT",
        ]:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

    # 잘못 수집된 moduparking 레코드 정리 (한 번만 실행)
    with get_conn() as conn:
        conn.execute("""
            DELETE FROM changes
            WHERE service_id = 'moduparking'
              AND source_type IN ('news', 'blog')
              AND title NOT LIKE '%모두의주차장%'
              AND title NOT LIKE '%모두의 주차장%'
              AND (summary IS NULL
                   OR (summary NOT LIKE '%모두의주차장%'
                       AND summary NOT LIKE '%모두의 주차장%'))
        """)


def import_services():
    json_path = DATA_DIR / "services.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    services = data.get("services", [])
    with get_conn() as conn:
        for s in services:
            conn.execute(
                """INSERT OR REPLACE INTO services
                   (id, name_ko, operator, category, meta_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (s["id"], s["name_ko"], s["operator"],
                 s.get("category"), json.dumps(s, ensure_ascii=False)),
            )
    return len(services)


# ──────────────────────────────────────────────
# 변경사항 CRUD
# ──────────────────────────────────────────────

def _norm_title(title: str) -> str:
    """뉴스 제목에서 '– 언론사명' 접미사 제거 (중복 감지용)."""
    return re.sub(r'\s*[\-–—]\s*[^\-–—]{1,35}$', '', title or '').strip()


def insert_change(
    service_id: str,
    published_at: str,
    source_type: str,
    change_type: str,
    title: str,
    summary: str | None = None,
    url: str | None = None,
    sentiment: str = "neutral",
    dedup_key: str | None = None,
) -> bool:
    cutoff = datetime.now() - timedelta(days=365)
    try:
        pub_str = str(published_at)[:10]
        pub_dt  = datetime.strptime(pub_str, "%Y-%m-%d")
        if pub_dt < cutoff:
            return False
    except ValueError:
        pub_str = datetime.now().strftime("%Y-%m-%d")

    raw      = dedup_key or (url or title or "").strip()
    url_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()

    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO changes
                   (service_id, published_at, source_type, change_type,
                    title, summary, url, url_hash, sentiment)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (service_id, pub_str, source_type, change_type,
                 title, summary, url, url_hash, sentiment),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def purge_old(days: int = 365) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM changes WHERE published_at < ?", (cutoff,)
        )
        return cur.rowcount


# ──────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────

def get_changes(service_id: str, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM changes
               WHERE service_id = ?
               ORDER BY published_at DESC, collected_at DESC
               LIMIT ?""",
            (service_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_status() -> dict:
    with get_conn() as conn:
        last_run = conn.execute(
            "SELECT run_at, status, items_added FROM collection_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

        today = datetime.now().strftime("%Y-%m-%d")
        today_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM changes WHERE DATE(collected_at) = ?",
            (today,),
        ).fetchone()

        cutoff_24h = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        per_svc = conn.execute(
            """SELECT service_id, COUNT(*) AS new_count
               FROM changes WHERE collected_at > ?
               GROUP BY service_id""",
            (cutoff_24h,),
        ).fetchall()

        crawled_today = bool(
            last_run and str(last_run["run_at"]).startswith(today)
        )

    return {
        "crawled_today": crawled_today,
        "last_run": dict(last_run) if last_run else None,
        "today_total": today_row["cnt"] if today_row else 0,
        "per_service_new": {r["service_id"]: r["new_count"] for r in per_svc},
    }


def get_summary() -> list[dict]:
    cutoff_24h = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.service_id, s.name_ko, c.change_type,
                      c.title, c.published_at, c.url, c.source_type, c.sentiment
               FROM changes c
               LEFT JOIN services s ON c.service_id = s.id
               WHERE c.collected_at > ?
               ORDER BY c.published_at DESC""",
            (cutoff_24h,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_services() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM services ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d.get("meta_json") or "{}")
        except Exception:
            d["meta"] = {}
        result.append(d)
    return result


def get_all_changes(limit: int = 300, change_type: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if change_type:
            rows = conn.execute(
                """SELECT c.*, s.name_ko, s.operator
                   FROM changes c
                   LEFT JOIN services s ON c.service_id = s.id
                   WHERE c.change_type = ?
                   ORDER BY c.published_at DESC, c.collected_at DESC
                   LIMIT ?""",
                (change_type, limit * 6,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.*, s.name_ko, s.operator
                   FROM changes c
                   LEFT JOIN services s ON c.service_id = s.id
                   ORDER BY c.published_at DESC, c.collected_at DESC
                   LIMIT ?""",
                (limit * 6,),
            ).fetchall()

    seen: set[str] = set()
    seen_norm: set[str] = set()
    results: list[dict] = []
    for row in rows:
        d = dict(row)
        url_key  = d.get("url") or ""
        raw_key  = url_key or f"{d['service_id']}|{d.get('title', '')}"
        # 뉴스/블로그는 정규화된 제목+날짜+서비스로 추가 중복 제거
        if d.get("source_type") in ("news", "blog"):
            norm = f"{d['service_id']}|{str(d.get('published_at',''))[:10]}|{_norm_title(d.get('title',''))}"
            if norm in seen_norm:
                continue
            seen_norm.add(norm)
        if raw_key and raw_key not in seen:
            seen.add(raw_key)
            results.append(d)
        if len(results) >= limit:
            break
    return results


def get_total_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM changes").fetchone()
        return row["cnt"] if row else 0


def get_service_counts() -> dict:
    """서비스별 전체 변경사항 수 반환."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT service_id, COUNT(*) AS cnt FROM changes GROUP BY service_id"
        ).fetchall()
    return {r["service_id"]: r["cnt"] for r in rows}


def get_app_stats() -> list[dict]:
    """앱 평점·리뷰수·버전 현황 조회 (운영사별 사용자 규모 파악용).
    SQLite가 비어있으면 data/app_info.json 파일로 폴백 (Railway 클라우드 모드용).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.service_id, a.platform, a.app_id,
                      a.rating, a.num_ratings, a.version,
                      a.update_notes, a.checked_at, s.name_ko
               FROM app_info a
               LEFT JOIN services s ON a.service_id = s.id
               ORDER BY a.service_id, a.platform"""
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

    # SQLite app_info 비어있으면 스냅샷 JSON 파일로 폴백
    json_path = DATA_DIR / "app_info.json"
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def search_features(query: str) -> list[dict]:
    features_path = DATA_DIR / "features.json"
    try:
        with open(features_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []

    q = query.lower().strip()
    if not q:
        return []

    results = []
    for feat in data.get("features", []):
        name     = feat.get("name_ko", "").lower()
        synonyms = [s.lower() for s in feat.get("synonyms", [])]
        if q in name or any(q in s for s in synonyms):
            results.append(feat)
    return results


# ──────────────────────────────────────────────
# HTML 스냅샷 (diff 감지용)
# ──────────────────────────────────────────────

def get_snapshot(service_id: str, url: str) -> tuple[str | None, str | None]:
    """이전 HTML 스냅샷 해시와 텍스트 반환. (hash, text) 튜플."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content_hash, content_text FROM html_snapshots WHERE service_id=? AND url=?",
            (service_id, url),
        ).fetchone()
        if row:
            return row["content_hash"], row["content_text"]
        return None, None


def save_snapshot(service_id: str, url: str, content_hash: str, content_text: str = ""):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO html_snapshots
               (service_id, url, content_hash, content_text, snapshot_at)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (service_id, url, content_hash, content_text),
        )


# ──────────────────────────────────────────────
# 앱 정보 (평점 / 버전 추적)
# ──────────────────────────────────────────────

def get_app_info(service_id: str, platform: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app_info WHERE service_id=? AND platform=?",
            (service_id, platform),
        ).fetchone()
        return dict(row) if row else None


def save_app_info(service_id: str, platform: str, app_id: str,
                  rating: float, num_ratings: int, version: str, update_notes: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO app_info
               (service_id, platform, app_id, rating, num_ratings, version, update_notes, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (service_id, platform, app_id, rating, num_ratings, version, update_notes),
        )
        conn.execute(
            """INSERT INTO app_info_history
               (service_id, platform, rating, num_ratings, version)
               VALUES (?, ?, ?, ?, ?)""",
            (service_id, platform, rating, num_ratings, version),
        )


# ──────────────────────────────────────────────
# 수집 로그
# ──────────────────────────────────────────────

def log_run(status: str, added: int, removed: int, notes: str = ""):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO collection_log (status, items_added, items_removed, notes)
               VALUES (?, ?, ?, ?)""",
            (status, added, removed, notes),
        )


# ──────────────────────────────────────────────
# CLI 모드
# ──────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    import_services()

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    dispatch = {
        "status":      lambda: get_status(),
        "changes":     lambda: get_changes(arg) if arg else [],
        "all_changes": lambda: get_all_changes(change_type=arg),
        "summary":     lambda: get_summary(),
        "search":      lambda: search_features(arg or ""),
        "services":    lambda: get_services(),
        "app_stats":   lambda: get_app_stats(),
    }

    fn = dispatch.get(cmd, lambda: {"error": f"알 수 없는 명령: {cmd}"})
    print(json.dumps(fn(), ensure_ascii=False, default=str))
