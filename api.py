"""
jobs.ge API სერვერი
FastAPI + SQLite
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from typing import Optional
import os
from scraper import run_scrape, DB_PATH, init_db

app = FastAPI(title="jobs.ge API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


@app.on_event("startup")
def on_startup():
    init_db()
    # პირველი გაშვებისას თუ ბაზა ცარიელია — გავპარსოთ
    con = get_db()
    count = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    con.close()
    if count == 0:
        import threading
        threading.Thread(target=run_scrape, daemon=True).start()


@app.get("/api/jobs")
def get_jobs(
    q: Optional[str] = Query(None, description="საძიებო სიტყვა"),
    category: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    salary: Optional[bool] = Query(None),
    vip: Optional[bool] = Query(None),
    sort: Optional[str] = Query("new", enum=["new", "deadline", "salary", "vip"]),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
):
    con = get_db()

    where = ["1=1"]
    params = []

    if q:
        where.append("(title LIKE ? OR company LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if category:
        where.append("category LIKE ?")
        params.append(f"%{category}%")
    if location:
        where.append("location LIKE ?")
        params.append(f"%{location}%")
    if salary is not None:
        where.append("salary = ?")
        params.append(1 if salary else 0)
    if vip is not None:
        where.append("vip = ?")
        params.append(1 if vip else 0)

    order = {
        "new": "id DESC",
        "deadline": "deadline ASC",
        "salary": "salary DESC, id DESC",
        "vip": "vip DESC, id DESC",
    }.get(sort, "id DESC")

    sql_count = f"SELECT COUNT(*) FROM jobs WHERE {' AND '.join(where)}"
    total = con.execute(sql_count, params).fetchone()[0]

    offset = (page - 1) * per_page
    sql = f"""
        SELECT * FROM jobs
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    rows = con.execute(sql, params + [per_page, offset]).fetchall()
    con.close()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "jobs": [dict(r) for r in rows],
    }


@app.get("/api/stats")
def get_stats():
    con = get_db()
    total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    salary = con.execute("SELECT COUNT(*) FROM jobs WHERE salary=1").fetchone()[0]
    vip = con.execute("SELECT COUNT(*) FROM jobs WHERE vip=1").fetchone()[0]
    is_new = con.execute("SELECT COUNT(*) FROM jobs WHERE is_new=1").fetchone()[0]
    cats = con.execute("""
        SELECT category, COUNT(*) as cnt FROM jobs
        WHERE category != ''
        GROUP BY category ORDER BY cnt DESC LIMIT 15
    """).fetchall()
    locs = con.execute("""
        SELECT location, COUNT(*) as cnt FROM jobs
        WHERE location != ''
        GROUP BY location ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    last_scrape = con.execute(
        "SELECT ended_at, total FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()

    return {
        "total": total,
        "salary": salary,
        "vip": vip,
        "is_new": is_new,
        "categories": [dict(r) for r in cats],
        "locations": [dict(r) for r in locs],
        "last_scrape": dict(last_scrape) if last_scrape else None,
    }


@app.post("/api/scrape")
def trigger_scrape():
    """ხელით გაშვება (ოჯახისთვის ან debug-ისთვის)"""
    import threading
    threading.Thread(target=run_scrape, daemon=True).start()
    return {"status": "scrape started"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
