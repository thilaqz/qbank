# QBank

A centralised question paper repository for college students. Papers are found
by college, semester, subject code and year. The PDFs live on Google Drive; this
application stores only the details you search by.

Only the administrator adds papers. Students never upload.

```
Phone / Browser
      │
      ▼
Cloudflare Quick Tunnel ──►  Nginx  ──►  Gunicorn  ──►  Flask  ──►  Oracle XE
                                                                    (in Docker,
      │                                                              metadata)
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

## Setting it up on Fedora-based Linux (Nobara, Fedora)

These steps were written for a Nobara Linux machine at home with no public IP
and no domain name. Oracle runs in a Docker container, and a free Cloudflare
Quick Tunnel makes the site reachable from outside the home network. Commands
use `dnf`, and SELinux stays **enforcing**.

### 1. System packages

```bash
sudo dnf upgrade --refresh -y
sudo dnf install -y python3 python3-pip nginx git curl wget unzip
python3 --version
nginx -v
```

`venv` ships with `python3` on Fedora, so there is no separate `python3-venv`
package.

### 2. Docker

```bash
sudo dnf install -y moby-engine
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

### 3. Oracle Database XE in a container

Installing Oracle XE natively on Fedora-based systems needs compatibility
packages and manual fixes, so the container is the simpler and more reliable
route. The application connects to it exactly as it would to a native install.

Choose an admin password for `SYS` and `SYSTEM` (letters and numbers only; no
`@`, quotes or spaces) and start the container:

```bash
sudo docker run -d --name qbank-oracle \
  --restart unless-stopped \
  -p 127.0.0.1:1521:1521 \
  -e ORACLE_PASSWORD='ChooseAdminPassword' \
  -v qbank-oracle-data:/opt/oracle/oradata \
  docker.io/gvenzl/oracle-xe:21-slim-faststart
```

- `127.0.0.1:1521:1521` keeps the database reachable from this machine only.
- The `qbank-oracle-data` volume keeps the data if the container is rebuilt.
- `--restart unless-stopped` brings the database back after a reboot.

The first start downloads the image and initialises the database, which takes
several minutes on a modest laptop. Watch for `DATABASE IS READY TO USE!`:

```bash
sudo docker logs -f qbank-oracle
```

### 4. Create the database user

```bash
sudo docker exec -it qbank-oracle sqlplus / as sysdba
```

Enter these one at a time at the `SQL>` prompt. Choose your own password
(letters and numbers; no `@`, quotes or spaces) and note it for `.env`:

```sql
ALTER SESSION SET CONTAINER = XEPDB1;
CREATE USER qbank IDENTIFIED BY "choose-a-strong-password"
  DEFAULT TABLESPACE users
  QUOTA UNLIMITED ON users;
GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE TO qbank;
EXIT;
```

`XEPDB1` is the pluggable database XE creates by default. The `ALTER SESSION`
line matters: without it the user is created in the container database, where
the application will not find it.

### 5. Put the project on the server

```bash
sudo mkdir -p /opt/qbank
sudo unzip -o ~/Downloads/qbank-project.zip -d /tmp/qbank-extract
sudo cp -a /tmp/qbank-extract/qbank/. /opt/qbank/
sudo rm -rf /tmp/qbank-extract

sudo useradd --system --home-dir /opt/qbank --shell /sbin/nologin qbank
sudo chown -R qbank:qbank /opt/qbank
ls -la /opt/qbank
```

### 6. Create the schema

Keep the password out of your shell history by reading it into a variable:

```bash
read -s -p "qbank DB password: " QPW; echo
cd /opt/qbank/sql
for f in 01_schema.sql 02_seed_master.sql 03_sample_papers.sql; do
  echo "=== $f ==="
  sudo docker exec -i qbank-oracle sqlplus -L -s qbank/"$QPW"@localhost:1521/XEPDB1 < "$f"
done
```

> **Warning:** `01_schema.sql` drops and recreates every table. Run it once.
> Running it again later deletes all papers.

Check the data. SQL*Plus needs one statement per line:

```bash
printf "SELECT COUNT(*) AS colleges FROM colleges;\nSELECT COUNT(*) AS papers FROM papers;\nEXIT;\n" \
  | sudo docker exec -i qbank-oracle sqlplus -L -s qbank/"$QPW"@localhost:1521/XEPDB1
```

### 7. Python environment

```bash
cd /opt/qbank
sudo -u qbank python3 -m venv venv
sudo -u qbank ./venv/bin/pip install --no-cache-dir --upgrade pip
sudo -u qbank ./venv/bin/pip install --no-cache-dir -r requirements.txt
sudo -u qbank ./venv/bin/python -c "import flask, oracledb; print('Python OK | Flask', flask.__version__, '| oracledb', oracledb.__version__)"
```

`oracledb` runs in thin mode, so Oracle Instant Client is **not** required.

### 8. Configuration

```bash
cd /opt/qbank
sudo -u qbank cp .env.example .env
KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sudo sed -i "s|^QBANK_SECRET_KEY=.*|QBANK_SECRET_KEY=$KEY|" .env
sudo nano .env        # set QBANK_DB_PASSWORD to the qbank database password
sudo chown qbank:qbank .env
sudo chmod 600 .env
```

Leave `QBANK_HTTPS=false` until the site is served over HTTPS (step 13).
Because `.env` is readable only by the `qbank` user, read it with `sudo`.

### 9. Administrator account

```bash
cd /opt/qbank
sudo -u qbank ./venv/bin/python create_admin.py
```

This is the login for `/admin/login`. It is separate from the database
password. It also confirms the application can reach Oracle.

### 10. Run the application as a service

```bash
sudo cp /opt/qbank/deploy/qbank.service /etc/systemd/system/qbank.service
sudo systemctl daemon-reload
sudo systemctl enable --now qbank
sudo systemctl status qbank --no-pager
curl http://127.0.0.1:8000/api/health
```

### 11. Nginx

Fedora-based systems read site files from `/etc/nginx/conf.d/`, not
`sites-available` and `sites-enabled`. This copies the project configuration
there, makes it the default site (so Fedora's welcome page does not take over)
and removes the domain name:

```bash
sudo sed -e 's/listen 80;/listen 80 default_server;/' \
         -e 's/server_name qbank.example.com;/server_name _;/' \
         /opt/qbank/deploy/nginx-qbank.conf | sudo tee /etc/nginx/conf.d/qbank.conf > /dev/null
```

SELinux blocks Nginx from reaching Gunicorn and from reading `/opt/qbank/static`
until you allow it:

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo dnf install -y policycoreutils-python-utils
sudo semanage fcontext -a -t httpd_sys_content_t "/opt/qbank/static(/.*)?"
sudo restorecon -Rv /opt/qbank/static
```

Start Nginx and check it:

```bash
sudo nginx -t
sudo systemctl enable --now nginx
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/static/css/qbank.css
```

Both requests should return `200 OK`.

### 12. Public access with a Cloudflare Quick Tunnel

A Quick Tunnel needs no domain and no Cloudflare account. The trade-off is that
the `trycloudflare.com` address **changes every time the tunnel restarts**, and
Cloudflare offers no uptime guarantee for Quick Tunnels.

```bash
sudo dnf install -y https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-x86_64.rpm
command -v cloudflared        # expect /usr/bin/cloudflared
```

Run the tunnel as a service so it starts on boot and restarts if it fails:

```bash
sudo tee /etc/systemd/system/qbank-tunnel.service > /dev/null <<'EOF'
[Unit]
Description=Cloudflare Quick Tunnel for QBank
After=network-online.target nginx.service
Wants=network-online.target

[Service]
Type=simple
DynamicUser=yes
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:80
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now qbank-tunnel
```

Find the current public address (run this after every restart):

```bash
sudo journalctl -u qbank-tunnel --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
```

Open it on a phone using mobile data to confirm it works from outside your
network.

### 13. Secure cookies

The tunnel serves the site over HTTPS, so mark the admin cookie as Secure:

```bash
sudo sed -i 's/^QBANK_HTTPS=.*/QBANK_HTTPS=true/' /opt/qbank/.env
sudo grep QBANK_HTTPS /opt/qbank/.env
sudo systemctl restart qbank
```

From now on, sign in to `/admin/login` through the **tunnel address**, not
`http://127.0.0.1`. A Secure cookie may be refused over plain HTTP, which looks
like a login that succeeds and then returns to the login page.

### 14. Check it survives a reboot

```bash
sudo reboot
```

Allow three to five minutes; Oracle is the slowest part to return. Then:

```bash
sudo docker ps --filter name=qbank-oracle --format '{{.Names}}: {{.Status}}'
systemctl is-active qbank nginx qbank-tunnel docker
curl http://127.0.0.1:8000/api/health
sudo journalctl -u qbank-tunnel --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
```

Expect the Oracle container to be `Up ... (healthy)`, four `active` lines, a
healthy response, and a **new** tunnel address.

---

## Day-to-day commands

```bash
# Current public address (changes after every restart)
sudo journalctl -u qbank-tunnel --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1

# Application logs
sudo journalctl -u qbank -n 40 --no-pager

# Restart after changing code or .env
sudo systemctl restart qbank

# Health of everything
systemctl is-active qbank nginx qbank-tunnel docker
sudo docker ps --filter name=qbank-oracle
```

Running it on a home laptop: disable sleep and keep the lid open and the charger
plugged in, or QBank goes offline until the machine wakes.

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

## Troubleshooting

**Search says "Could not load the papers" and the log shows
`ORA-00904: "PAGE_COUNT": invalid identifier`.**
The `v_paper_details` view must select `p.page_count`. The current
`sql/01_schema.sql` already does. If you have an older copy, add
`p.page_count,` after `p.exam_type,` in the view and recreate only the view
(this leaves your tables and data alone):

```bash
sed -n '/CREATE OR REPLACE VIEW/,/;$/p' sql/01_schema.sql \
  | sudo docker exec -i qbank-oracle sqlplus -L -s qbank/"$QPW"@localhost:1521/XEPDB1
```

**`curl http://127.0.0.1/static/css/qbank.css` returns 403.**
SELinux or file permissions. Repeat the `semanage fcontext` and `restorecon`
commands in step 11.

**Nginx returns 502 Bad Gateway.**
Either Gunicorn is not running (`sudo systemctl status qbank`) or SELinux is
blocking the connection (`sudo setsebool -P httpd_can_network_connect 1`).

**The admin login succeeds, then returns to the login page.**
You are signing in over plain HTTP while `QBANK_HTTPS=true`. Use the tunnel
address instead.

**`create_admin.py` says the database did not answer.**
Check that the container is `Up`, and that `QBANK_DB_DSN` in `.env` is
`localhost:1521/XEPDB1` and the password is correct.

**The public address stopped working.**
Quick Tunnel addresses change on every restart. Print the current one with the
command under "Day-to-day commands".

---

## Running the tests

```bash
cd /opt/qbank
sudo -u qbank ./venv/bin/python -m unittest discover -s tests -v
```

The database layer is stubbed, so these run on any machine without Oracle.

---

## Security notes

- Passwords are stored as PBKDF2 hashes from `werkzeug.security`, never as text.
- Every statement uses bind variables.
- The admin session cookie is HttpOnly and SameSite=Lax. Set `QBANK_HTTPS=true`
  once the site is served over TLS so the cookie is marked Secure too.
- `.env` is excluded by `.gitignore` and is `chmod 600`, owned by the `qbank`
  user. Never commit real credentials.
- Oracle listens on `127.0.0.1` only; it is never exposed to the network.
- The database user has no `DROP ANY` or administrative privileges.
- The `qbank` system account has no login shell.

---

## Ideas if you extend it

- Full text search across subject names using Oracle Text.
- A "most viewed this week" list, since `view_count` is already recorded.
- Bulk add: paste a Drive folder listing and record several papers at once.
- Per-college regulation defaults so the administrator types `R2021` less often.
- A permanent address with a Cloudflare named tunnel (needs a domain).
- Scheduled database backups of the `qbank-oracle-data` volume.
