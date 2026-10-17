"""Every SQL statement QBank runs lives here.

Keeping the queries in one module means the route handlers stay readable and
the database work can be reviewed in one place.

On optional filters: the search screen lets a student leave the semester,
subject code and year blank, and blank means 'do not filter'. Rather than
writing `(:semester IS NULL OR semester = :semester)` for every column, the
WHERE clause is assembled from only the filters that were actually supplied.
That keeps the bind variables correctly typed and lets Oracle choose a better
execution plan for each combination. Every value is still bound, never
concatenated, so the statement remains injection-safe.
"""

import db

# --------------------------------------------------------------------------
# Public lookups
# --------------------------------------------------------------------------


def list_states() -> list[dict]:
    return db.query(
        "SELECT state_id, state_name FROM states ORDER BY state_name"
    )


def list_colleges(state_id: int) -> list[dict]:
    return db.query(
        """
        SELECT college_id, college_name, short_name, district, university
        FROM   colleges
        WHERE  state_id = :state_id
        ORDER  BY college_name
        """,
        {"state_id": state_id},
    )


def get_college(college_id: int) -> dict | None:
    return db.query_one(
        """
        SELECT c.college_id, c.college_name, c.short_name, c.district,
               c.university, s.state_id, s.state_name
        FROM   colleges c JOIN states s ON s.state_id = c.state_id
        WHERE  c.college_id = :college_id
        """,
        {"college_id": college_id},
    )


def available_semesters(college_id: int) -> list[int]:
    rows = db.query(
        """
        SELECT DISTINCT semester
        FROM   papers
        WHERE  college_id = :college_id AND is_active = 'Y' AND semester IS NOT NULL
        ORDER  BY semester
        """,
        {"college_id": college_id},
    )
    return [int(r["semester"]) for r in rows]


def available_years(college_id: int) -> list[int]:
    rows = db.query(
        """
        SELECT DISTINCT paper_year
        FROM   papers
        WHERE  college_id = :college_id AND is_active = 'Y' AND paper_year IS NOT NULL
        ORDER  BY paper_year DESC
        """,
        {"college_id": college_id},
    )
    return [int(r["paper_year"]) for r in rows]


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

_SEARCH_SELECT = """
SELECT paper_id, drive_file_id, semester, paper_year, exam_month, exam_type,
       page_count, subject_code, subject_name, regulation, dept_code,
       college_id, college_name, college_short_name, state_name, view_count
FROM   v_paper_details
"""


def search_papers(
    college_id: int,
    semester: int | None = None,
    subject_code: str | None = None,
    paper_year: int | None = None,
    exam_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses = ["is_active = 'Y'", "college_id = :college_id"]
    params: dict = {"college_id": college_id, "row_limit": limit}

    if semester is not None:
        clauses.append("semester = :semester")
        params["semester"] = semester

    if subject_code:
        # Partial match, so 'CS35' finds CS3501 and CS3591. The index on
        # UPPER(subject_code) is used for the prefix portion of the scan.
        clauses.append(
            "(UPPER(subject_code) LIKE UPPER(:subject_code) || '%'"
            " OR UPPER(subject_name) LIKE '%' || UPPER(:subject_code) || '%')"
        )
        params["subject_code"] = subject_code

    if paper_year is not None:
        clauses.append("paper_year = :paper_year")
        params["paper_year"] = paper_year

    if exam_type:
        clauses.append("exam_type = :exam_type")
        params["exam_type"] = exam_type

    sql = (
        _SEARCH_SELECT
        + "WHERE " + " AND ".join(clauses)
        + """
        ORDER BY paper_year DESC NULLS LAST,
                 semester     ASC  NULLS LAST,
                 subject_code ASC
        FETCH FIRST :row_limit ROWS ONLY
        """
    )
    return db.query(sql, params)


def get_paper(paper_id: int) -> dict | None:
    return db.query_one(
        _SEARCH_SELECT + "WHERE paper_id = :paper_id AND is_active = 'Y'",
        {"paper_id": paper_id},
    )


def record_view(paper_id: int) -> None:
    db.execute(
        "UPDATE papers SET view_count = view_count + 1 WHERE paper_id = :paper_id",
        {"paper_id": paper_id},
    )


# --------------------------------------------------------------------------
# Administration
# --------------------------------------------------------------------------


def get_admin_by_username(username: str) -> dict | None:
    return db.query_one(
        """
        SELECT admin_id, username, password_hash, full_name
        FROM   admin_users
        WHERE  UPPER(username) = UPPER(:username)
        """,
        {"username": username},
    )


def touch_last_login(admin_id: int) -> None:
    db.execute(
        "UPDATE admin_users SET last_login = SYSTIMESTAMP WHERE admin_id = :admin_id",
        {"admin_id": admin_id},
    )


def list_departments() -> list[dict]:
    return db.query(
        "SELECT dept_id, dept_code, dept_name FROM departments ORDER BY dept_name"
    )


def find_subject(subject_code: str, regulation: str) -> dict | None:
    return db.query_one(
        """
        SELECT subject_id, subject_code, subject_name, semester, regulation
        FROM   subjects
        WHERE  UPPER(subject_code) = UPPER(:subject_code)
        AND    UPPER(regulation)   = UPPER(:regulation)
        """,
        {"subject_code": subject_code, "regulation": regulation},
    )


def create_subject(
    subject_code: str,
    subject_name: str,
    dept_id: int | None,
    semester: int | None,
    regulation: str,
) -> int:
    return db.insert_returning_id(
        """
        INSERT INTO subjects (subject_code, subject_name, dept_id, semester, regulation)
        VALUES (:subject_code, :subject_name, :dept_id, :semester, :regulation)
        RETURNING subject_id INTO :id
        """,
        {
            "subject_code": subject_code.upper(),
            "subject_name": subject_name,
            "dept_id": dept_id,
            "semester": semester,
            "regulation": regulation.upper(),
        },
    )


def get_or_create_subject(
    subject_code: str,
    subject_name: str,
    dept_id: int | None,
    semester: int | None,
    regulation: str = "R2021",
) -> int:
    existing = find_subject(subject_code, regulation)
    if existing:
        return int(existing["subject_id"])
    return create_subject(subject_code, subject_name, dept_id, semester, regulation)


def paper_exists(college_id, subject_id, paper_year, exam_month, exam_type) -> bool:
    row = db.query_one(
        """
        SELECT paper_id FROM papers
        WHERE college_id = :college_id
          AND subject_id = :subject_id
          AND NVL(paper_year, -1) = NVL(:paper_year, -1)
          AND NVL(exam_month, '-') = NVL(:exam_month, '-')
          AND exam_type = :exam_type
        """,
        {
            "college_id": college_id,
            "subject_id": subject_id,
            "paper_year": paper_year,
            "exam_month": exam_month,
            "exam_type": exam_type,
        },
    )
    return row is not None


def insert_paper(
    college_id: int,
    subject_id: int,
    semester: int | None,
    paper_year: int | None,
    exam_month: str | None,
    exam_type: str,
    drive_file_id: str,
    page_count: int | None,
) -> int:
    return db.insert_returning_id(
        """
        INSERT INTO papers (college_id, subject_id, semester, paper_year,
                            exam_month, exam_type, drive_file_id, page_count)
        VALUES (:college_id, :subject_id, :semester, :paper_year,
                :exam_month, :exam_type, :drive_file_id, :page_count)
        RETURNING paper_id INTO :id
        """,
        {
            "college_id": college_id,
            "subject_id": subject_id,
            "semester": semester,
            "paper_year": paper_year,
            "exam_month": exam_month,
            "exam_type": exam_type,
            "drive_file_id": drive_file_id,
            "page_count": page_count,
        },
    )


def recent_papers(limit: int = 25) -> list[dict]:
    return db.query(
        _SEARCH_SELECT
        + """
        WHERE is_active = 'Y'
        ORDER BY added_on DESC
        FETCH FIRST :row_limit ROWS ONLY
        """,
        {"row_limit": limit},
    )


def retire_paper(paper_id: int) -> int:
    """Soft delete. The row is kept so view counts and history survive."""
    return db.execute(
        "UPDATE papers SET is_active = 'N' WHERE paper_id = :paper_id",
        {"paper_id": paper_id},
    )


def create_college(
    state_id: int,
    college_name: str,
    short_name: str | None,
    district: str | None,
    university: str | None,
) -> int:
    return db.insert_returning_id(
        """
        INSERT INTO colleges (state_id, college_name, short_name, district, university)
        VALUES (:state_id, :college_name, :short_name, :district, :university)
        RETURNING college_id INTO :id
        """,
        {
            "state_id": state_id,
            "college_name": college_name,
            "short_name": short_name,
            "district": district,
            "university": university,
        },
    )


def statistics() -> dict:
    row = db.query_one(
        """
        SELECT (SELECT COUNT(*) FROM papers WHERE is_active = 'Y') AS paper_count,
               (SELECT COUNT(*) FROM colleges)                      AS college_count,
               (SELECT COUNT(*) FROM subjects)                      AS subject_count,
               (SELECT NVL(SUM(view_count), 0) FROM papers)         AS total_views
        FROM dual
        """
    )
    return {k: int(v) for k, v in (row or {}).items()}
