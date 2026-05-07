"""
jobs.ge API სერვერი - CORS fixed
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sqlite3
from typing import Optional
import threading
from scraper import run_scrape, DB_PATH, init_db

app = FastAPI(title="jobs.ge API", version="1.0")

# CORS — ყველა origin-ს ნებადართული
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


@app.on_event("startup")
def on_startup():
    init_db()
    con = get_db()
    count = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    con.close()
    if count == 0:
        threading.Thread(target=run_scrape, daemon=True).start()


@app.get("/")
def root():
    return {"status": "ok", "service": "jobs.ge API"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/jobs")
def get_jobs(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    salary: Optional[bool] = Query(None),
    vip: Optional[bool] = Query(None),
    sort: Optional[str] = Query("new"),
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

    total = con.execute(
        f"SELECT COUNT(*) FROM jobs WHERE {' AND '.join(where)}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    rows = con.execute(
        f"SELECT * FROM jobs WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()
    con.close()

    return JSONResponse({
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "jobs": [dict(r) for r in rows],
    })


@app.get("/api/stats")
def get_stats():
    con = get_db()
    total = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    salary = con.execute("SELECT COUNT(*) FROM jobs WHERE salary=1").fetchone()[0]
    vip = con.execute("SELECT COUNT(*) FROM jobs WHERE vip=1").fetchone()[0]
    is_new = con.execute("SELECT COUNT(*) FROM jobs WHERE is_new=1").fetchone()[0]
    last = con.execute(
        "SELECT ended_at, total FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()

    return JSONResponse({
        "total": total,
        "salary": salary,
        "vip": vip,
        "is_new": is_new,
        "last_scrape": dict(last) if last else None,
    })


@app.post("/api/scrape")
def trigger_scrape():
    threading.Thread(target=run_scrape, daemon=True).start()
    return {"status": "scrape started"}
