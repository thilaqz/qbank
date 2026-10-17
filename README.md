# QBank

A centralised question paper repository for college students. Papers are found
by college, semester, subject code and year. The PDFs live on Google Drive; this
application stores only the details you search by.

Only the administrator adds papers. Students never upload.

```
Browser  ──►  Nginx  ──►  Gunicorn  ──►  Flask  ──►  Oracle XE
   │                                                  (metadata)
   └──────────────────►  Google Drive  (the PDF itself)
```

---

## Files

| Path | What it holds |
|---|---|
| `app.py` | Routes: pages, the public JSON API, the admin API |
| `repository.py` | Every SQL statement the application runs |
| `db.py` | Oracle connection pool and query helpers |
| `config.py` | Settings, read from the environment |
| `utils.py` | Drive link parsing, input coercion |
| `create_admin.py` | One-off script to create the administrator account |
| `sql/01_schema.sql` | Tables, constraints, indexes, the `v_paper_details` view |
| `sql/02_seed_master.sql` | States, colleges, departments, subjects |
| `sql/03_sample_papers.sql` | Demonstration paper rows |
| `templates/` | Jinja2 page templates |
| `static/css/qbank.css` | The entire stylesheet |
| `static/js/` | `select.js`, `results.js`, `admin.js` |
| `tests/test_routes.py` | Route tests that run without a database |
| `deploy/` | systemd unit and Nginx site configuration |

---

## Setting it up on Ubuntu Server

### 1. Oracle Database XE

Install Oracle Database 21c Express Edition, then create the application user.
Connect as a privileged user:

```bash
sqlplus sys/YourSysPassword@localhost:1521/XEPDB1 as sysdba
```

```sql
CREATE USER qbank IDENTIFIED BY "choose-a-strong-password"
  DEFAULT TABLESPACE users
  QUOTA UNLIMITED ON users;

GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE TO qbank;
```

`XEPDB1` is the pluggable database XE creates by default. Connecting to `XE`
instead reaches the container database, where the user will not exist.

### 2. Create the schema

```bash
sqlplus qbank/your-password@localhost:1521/XEPDB1 @sql/01_schema.sql
sqlplus qbank/your-password@localhost:1521/XEPDB1 @sql/02_seed_master.sql
sqlplus qbank/your-password@localhost:1521/XEPDB1 @sql/03_sample_papers.sql
```

### 3. Python environment

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx

cd /opt/qbank
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`oracledb` runs in thin mode, so Oracle Instant Client is **not** required.

### 4. Configuration

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # paste as QBANK_SECRET_KEY
nano .env
chmod 600 .env
```

### 5. Administrator account

```bash
python create_admin.py
```

### 6. Run it

Development:

```bash
python app.py          # http://127.0.0.1:5000
```

Production:

```bash
sudo cp deploy/qbank.service /etc/systemd/system/
sudo cp deploy/nginx-qbank.conf /etc/nginx/sites-available/qbank
sudo ln -s /etc/nginx/sites-available/qbank /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl daemon-reload && sudo systemctl enable --now qbank
```

Check it is alive:

```bash
curl http://127.0.0.1:8000/api/health
```

---

## Adding a paper

1. Upload the PDF to your QBank folder on Google Drive.
2. Right click it, Share, and set **anyone with the link** to **Viewer**.
3. Copy the link.
4. Sign in at `/admin/login`, paste the link, fill in the code, semester and
   year, and add it.

The file id is extracted from the link and stored on its own. Storing the id
rather than the whole URL means a change in Drive's URL format never requires a
data migration.

**Drive's daily quota.** A file that is downloaded very heavily will start
returning "quota exceeded" until it resets. The paper page therefore embeds the
`/preview` viewer by default, which is much gentler on the quota than a direct
download. If a paper is likely to be in heavy demand, keep a second copy in a
different Drive account as a fallback.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/states` | All states |
| GET | `/api/colleges?state=<id>` | Colleges in one state |
| GET | `/api/filters?college=<id>` | Semesters and years that actually have papers |
| GET | `/api/papers?college=<id>&semester=&code=&year=&type=` | Search. Every filter except `college` is optional |
| GET | `/api/health` | Database reachability |
| GET | `/api/admin/recent` | Recently added papers (sign-in required) |
| POST | `/api/admin/papers` | Add a paper (sign-in required) |
| DELETE | `/api/admin/papers/<id>` | Retire a paper (sign-in required) |
| POST | `/api/admin/colleges` | Add a college (sign-in required) |

### Optional filters

A student may leave semester, subject code and year blank, and blank means "do
not filter". Rather than writing `(:semester IS NULL OR semester = :semester)`
for every column, the `WHERE` clause is assembled from only the filters that
were supplied. That keeps every bind variable correctly typed and lets Oracle
pick a good plan for each combination. Values are always bound, never
concatenated into the SQL text, and `tests/test_routes.py` asserts exactly that.

---

## Running the tests

```bash
python -m unittest discover -s tests -v
```

The database layer is stubbed, so these run on any machine without Oracle.

---

## Security notes

- Passwords are stored as PBKDF2 hashes from `werkzeug.security`, never as text.
- Every statement uses bind variables.
- The admin session cookie is HttpOnly and SameSite=Lax. Set `QBANK_HTTPS=true`
  once the site is served over TLS so the cookie is marked Secure too.
- `.env` is excluded by `.gitignore`. Never commit real credentials.
- The database user has no `DROP ANY` or administrative privileges.

---

## Ideas if you extend it

- Full text search across subject names using Oracle Text.
- A "most viewed this week" list, since `view_count` is already recorded.
- Bulk add: paste a Drive folder listing and record several papers at once.
- Per-college regulation defaults so the administrator types `R2021` less often.
