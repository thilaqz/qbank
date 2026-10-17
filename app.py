"""QBank -- a centralised question paper repository.

Three-tier application:
  presentation  static HTML/CSS/JavaScript served from /static
  application   this Flask module, exposing a JSON API
  data          Oracle Database XE, reached through repository.py

The PDFs themselves are not stored here. Each paper record holds a Google
Drive file id; the browser loads the document straight from Drive.
"""

from functools import wraps
import logging

from flask import (
    Flask, jsonify, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash

import db
import repository as repo
from config import Config
from utils import (
    as_int, clean_text, drive_download_url, drive_preview_url, drive_view_url,
    extract_drive_file_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("qbank")

app = Flask(__name__)
app.config.from_object(Config)

with app.app_context():
    try:
        db.init_pool()
    except Exception as exc:  # the site should still start and say what is wrong
        log.error("Could not open the Oracle connection pool: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXAM_TYPES = ("Semester", "Arrear", "Internal", "Model")


def admin_required(view):
    """Guard for every administrative route."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            if request.path.startswith("/api/"):
                return jsonify(error="Sign in to continue."), 401
            return redirect(url_for("admin_login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def paper_payload(row: dict) -> dict:
    """Shape a database row for the browser, adding the Drive URLs."""
    file_id = row["drive_file_id"]
    return {
        "paper_id": int(row["paper_id"]),
        "subject_code": row["subject_code"],
        "subject_name": row["subject_name"],
        "regulation": row.get("regulation"),
        "department": row.get("dept_code"),
        "semester": int(row["semester"]) if row.get("semester") else None,
        "year": int(row["paper_year"]) if row.get("paper_year") else None,
        "month": row.get("exam_month"),
        "exam_type": row.get("exam_type"),
        "pages": int(row["page_count"]) if row.get("page_count") else None,
        "college": row.get("college_short_name") or row.get("college_name"),
        "preview_url": drive_preview_url(file_id),
        "view_url": drive_view_url(file_id),
        "download_url": drive_download_url(file_id),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/search")
def search_page():
    """Second step: filters and results for one college."""
    college_id = as_int(request.args.get("college"))
    if college_id is None:
        return redirect(url_for("home"))
    college = repo.get_college(college_id)
    if college is None:
        return redirect(url_for("home"))
    return render_template("search.html", college=college)


@app.route("/paper/<int:paper_id>")
def paper_page(paper_id: int):
    row = repo.get_paper(paper_id)
    if row is None:
        return render_template("not_found.html"), 404
    repo.record_view(paper_id)
    return render_template("paper.html", paper=paper_payload(row), raw=row)


@app.route("/about")
def about_page():
    return render_template("about.html", stats=_safe_stats())


def _safe_stats() -> dict:
    try:
        return repo.statistics()
    except Exception:
        return {"paper_count": 0, "college_count": 0, "subject_count": 0,
                "total_views": 0}


# ---------------------------------------------------------------------------
# Public JSON API
# ---------------------------------------------------------------------------

@app.get("/api/states")
def api_states():
    return jsonify([
        {"id": int(r["state_id"]), "name": r["state_name"]}
        for r in repo.list_states()
    ])


@app.get("/api/colleges")
def api_colleges():
    state_id = as_int(request.args.get("state"))
    if state_id is None:
        return jsonify(error="Choose a state first."), 400
    return jsonify([
        {
            "id": int(r["college_id"]),
            "name": r["college_name"],
            "short_name": r["short_name"],
            "district": r["district"],
            "university": r["university"],
        }
        for r in repo.list_colleges(state_id)
    ])


@app.get("/api/filters")
def api_filters():
    """Semesters and years that actually have papers, for this college."""
    college_id = as_int(request.args.get("college"))
    if college_id is None:
        return jsonify(error="Choose a college first."), 400
    return jsonify({
        "semesters": repo.available_semesters(college_id),
        "years": repo.available_years(college_id),
        "exam_types": list(EXAM_TYPES),
    })


@app.get("/api/papers")
def api_papers():
    """The search endpoint. Every filter except the college is optional."""
    college_id = as_int(request.args.get("college"))
    if college_id is None:
        return jsonify(error="Choose a college first."), 400

    rows = repo.search_papers(
        college_id=college_id,
        semester=as_int(request.args.get("semester"), 1, 10),
        subject_code=clean_text(request.args.get("code"), 20),
        paper_year=as_int(request.args.get("year"), 1990, 2100),
        exam_type=(request.args.get("type")
                   if request.args.get("type") in EXAM_TYPES else None),
        limit=Config.RESULT_LIMIT,
    )
    return jsonify({
        "count": len(rows),
        "limit": Config.RESULT_LIMIT,
        "papers": [paper_payload(r) for r in rows],
    })


@app.get("/api/health")
def api_health():
    ok = db.healthy()
    return jsonify(database="up" if ok else "down"), (200 if ok else 503)


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    if request.method == "GET":
        if session.get("admin_id"):
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error=None)

    username = clean_text(request.form.get("username"), 40) or ""
    password = request.form.get("password") or ""
    admin = repo.get_admin_by_username(username)

    if admin is None or not check_password_hash(admin["password_hash"], password):
        log.warning("Failed sign-in for username %r from %s",
                    username, request.remote_addr)
        return render_template(
            "admin_login.html",
            error="That username and password don't match. Try again.",
        ), 401

    session.clear()
    session["admin_id"] = int(admin["admin_id"])
    session["admin_name"] = admin["full_name"] or admin["username"]
    session.permanent = True
    repo.touch_last_login(int(admin["admin_id"]))
    return redirect(request.args.get("next") or url_for("admin_dashboard"))


@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        admin_name=session.get("admin_name"),
        stats=_safe_stats(),
        states=repo.list_states(),
        departments=repo.list_departments(),
        exam_types=EXAM_TYPES,
    )


@app.get("/api/admin/recent")
@admin_required
def api_admin_recent():
    return jsonify([paper_payload(r) for r in repo.recent_papers(25)])


@app.post("/api/admin/papers")
@admin_required
def api_admin_add_paper():
    """Record one question paper.

    The PDF is already on Google Drive; what arrives here is its link plus the
    metadata needed to find it again.
    """
    data = request.get_json(silent=True) or {}

    college_id = as_int(data.get("college_id"))
    subject_code = clean_text(data.get("subject_code"), 20)
    subject_name = clean_text(data.get("subject_name"), 150)
    drive_link = clean_text(data.get("drive_link"), 400)

    if college_id is None:
        return jsonify(error="Choose a college."), 400
    if not subject_code:
        return jsonify(error="Enter the subject code."), 400
    if not drive_link:
        return jsonify(error="Paste the Google Drive link."), 400

    file_id = extract_drive_file_id(drive_link)
    if file_id is None:
        return jsonify(
            error="That doesn't look like a Drive link. Copy the address from "
                  "the file's Share dialog."
        ), 400

    if repo.get_college(college_id) is None:
        return jsonify(error="That college is not in the list."), 400

    semester = as_int(data.get("semester"), 1, 10)
    regulation = clean_text(data.get("regulation"), 10) or "R2021"
    dept_id = as_int(data.get("dept_id"))

    subject_id = repo.get_or_create_subject(
        subject_code=subject_code,
        subject_name=subject_name or subject_code,
        dept_id=dept_id,
        semester=semester,
        regulation=regulation,
    )

    paper_year = as_int(data.get("year"), 1990, 2100)
    exam_month = clean_text(data.get("month"), 20)
    exam_type = data.get("exam_type")
    if exam_type not in EXAM_TYPES:
        exam_type = "Semester"

    if repo.paper_exists(college_id, subject_id, paper_year, exam_month, exam_type):
        return jsonify(
            error="This paper is already in the repository."
        ), 409

    paper_id = repo.insert_paper(
        college_id=college_id,
        subject_id=subject_id,
        semester=semester,
        paper_year=paper_year,
        exam_month=exam_month,
        exam_type=exam_type,
        drive_file_id=file_id,
        page_count=as_int(data.get("pages"), 1, 99),
    )
    log.info("Paper %s added by admin %s", paper_id, session.get("admin_name"))
    return jsonify(paper_id=paper_id, message="Paper added."), 201


@app.delete("/api/admin/papers/<int:paper_id>")
@admin_required
def api_admin_remove_paper(paper_id: int):
    affected = repo.retire_paper(paper_id)
    if affected == 0:
        return jsonify(error="No such paper."), 404
    return jsonify(message="Paper removed.")


@app.post("/api/admin/colleges")
@admin_required
def api_admin_add_college():
    data = request.get_json(silent=True) or {}
    state_id = as_int(data.get("state_id"))
    college_name = clean_text(data.get("college_name"), 150)
    if state_id is None or not college_name:
        return jsonify(error="A state and a college name are needed."), 400
    college_id = repo.create_college(
        state_id=state_id,
        college_name=college_name,
        short_name=clean_text(data.get("short_name"), 40),
        district=clean_text(data.get("district"), 60),
        university=clean_text(data.get("university"), 120),
    )
    return jsonify(college_id=college_id, message="College added."), 201


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def handle_404(_):
    if request.path.startswith("/api/"):
        return jsonify(error="No such endpoint."), 404
    return render_template("not_found.html"), 404


@app.errorhandler(500)
def handle_500(exc):
    log.exception("Unhandled error: %s", exc)
    if request.path.startswith("/api/"):
        return jsonify(error="The server could not complete that request."), 500
    return render_template("error.html"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
