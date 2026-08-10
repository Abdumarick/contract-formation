# Hotel Contract Parser deployment guide

This guide covers local testing, office-network deployment, and public cloud
deployment. Commands must be run from the project folder unless stated otherwise.

## 1. What the application requires

### Application requirements

- Python and `pip` (use the same Python version used to test the project)
- The packages listed in `requirements.txt`
- Poppler, required by `pdf2image` to convert scanned PDF pages to images
- Tesseract OCR, required by `pytesseract` to read scanned documents
- Read/write access to the project `uploads` and `outputs` directories
- Persistent disk storage for those directories in production

### Suggested host capacity

OCR is CPU- and memory-intensive. A practical starting point for a small office is:

- 2 CPU cores minimum; 4 cores are preferable for simultaneous OCR jobs
- 4 GB RAM minimum; 8 GB is preferable for large PDFs
- At least 20 GB persistent disk, adjusted for expected contract volume and backups
- A stable private-office or cloud network connection

Monitor CPU, memory, and disk use after launch. Increase capacity if several users
process PDFs simultaneously.

### Network and security requirements

- Local-only testing: no firewall change is required
- Trusted office LAN: allow TCP port 8081 on Private networks only
- Public cloud: allow public ports 80 and 443 only; redirect 80 to HTTPS 443
- Do not expose the application server's port 8081 directly to the internet
- Use HTTPS for every cloud or remote deployment
- Store credentials as environment variables or platform secrets, never in Git
- Back up `uploads` and `outputs`

## 2. Configuration values and when to change them

| Setting | Example | When to set or change it | Purpose |
|---|---|---|---|
| `APP_USERNAME` | `contracts-admin` | Set before every new deployment; change when access responsibility changes | Username shown by the browser login prompt |
| `APP_PASSWORD` | a long unique password | Set before deployment; rotate after exposure or staff access changes | Protects all pages and files |
| `APP_SECRET_KEY` | a random 48+ character value | Generate once per environment; rotate after suspected compromise | Signs Flask security/session data |
| `APP_HTTPS` | `true` | Set to `true` when the public address uses HTTPS | Marks browser session cookies as HTTPS-only |
| `APP_HOST` | `127.0.0.1` | Only applies when running `python web_interface.py` | Chooses which interface Flask's development server uses |
| `APP_PORT` | `8081` | Change only if port 8081 conflicts with another service | Changes the development server port |
| `LOG_LEVEL` | `INFO` | Normally leave as `INFO`; temporarily use `DEBUG` during diagnosis | Controls server log detail |

Generate an application secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use different secrets and passwords for local testing and production. Restart the
application after changing any environment variable; the running process does not
reload them automatically.

## 3. First-time installation on Windows

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install Poppler and Tesseract OCR using approved Windows installers or your package
manager. Add their executable directories to the system `PATH`, then open a new
PowerShell window and verify:

```powershell
pdftoppm -v
tesseract --version
```

Both commands must work for scanned-PDF OCR. Text-based PDFs may work without OCR,
but that is not a complete production installation.

## 4. Local login test on one computer

Run:

```powershell
.\run_web.bat
```

Example answers:

```text
Office username: Admin
Office password: use-a-temporary-test-password
```

Open `http://localhost:8081`. The browser should ask for those credentials.

Test all of the following:

1. Correct credentials open the application.
2. A wrong password is rejected.
3. `/library` also requires login.
4. A PDF can be uploaded and processed.
5. A CSV can be downloaded and reloaded.
6. Deletion works only after confirmation in the interface.

Keep the command window open. Press Ctrl+C to stop the server. Credentials entered
by `run_web.bat` apply only to that running process and are requested again next time.

## 5. Trusted office-network deployment

This option is for staff connected to the same trusted private LAN. It is not for
guest Wi-Fi, remote workers, router port forwarding, or internet access.

1. Give the server computer a reserved/static LAN address in the router or DHCP
   configuration so its address does not unexpectedly change.
2. Confirm Windows identifies the office connection as a Private network.
3. Start `.\run_web.bat` and enter the production office credentials.
4. Run `ipconfig` and find the active adapter's IPv4 address.
5. Allow TCP 8081 through Windows Firewall for Private networks only.
6. From another office computer, open the server address.

Example:

```text
Server IPv4 address: 192.168.1.25
Office URL: http://192.168.1.25:8081
```

The host must remain powered on, awake, and connected. For automatic startup after a
reboot, configure an approved Windows service or Task Scheduler entry that sets the
environment variables and runs:

```powershell
python -m waitress --host=0.0.0.0 --port=8081 --threads=4 web_interface:app
```

Plain office HTTP does not encrypt credentials or contract data. Use this only on a
trusted and properly secured LAN. Use the cloud/HTTPS design below for remote access.

## 6. Cloud deployment architecture

Use this request path:

```text
User browser
    -> HTTPS port 443
    -> Nginx, IIS, load balancer, or managed cloud proxy
    -> private localhost port 8081
    -> Waitress
    -> Flask application
    -> persistent uploads/outputs storage
```

The proxy handles the public domain and TLS certificate. Waitress must bind to
`127.0.0.1`, not `0.0.0.0`, when it is behind a proxy on the same server.

## 7. Linux cloud server example

### Install operating-system packages

For Ubuntu/Debian:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip poppler-utils tesseract-ocr nginx
```

Create the environment and install Python packages:

```bash
cd /opt/hotel-contract-parser
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### Create production secrets

Create a root-readable environment file such as `/etc/hotel-parser.env`:

```text
APP_USERNAME=contracts-admin
APP_PASSWORD=REPLACE_WITH_A_LONG_UNIQUE_PASSWORD
APP_SECRET_KEY=REPLACE_WITH_OUTPUT_FROM_THE_SECRET_GENERATOR
APP_HTTPS=true
LOG_LEVEL=INFO
```

Change all `REPLACE_...` values before the first start. Do not commit this file.
Restrict it so only the service administrator can read it.

### Run as a service

Example `/etc/systemd/system/hotel-parser.service`:

```ini
[Unit]
Description=Hotel Contract Parser
After=network.target

[Service]
Type=simple
User=hotelparser
Group=hotelparser
WorkingDirectory=/opt/hotel-contract-parser
EnvironmentFile=/etc/hotel-parser.env
ExecStart=/opt/hotel-contract-parser/.venv/bin/python -m waitress --host=127.0.0.1 --port=8081 --threads=4 web_interface:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The `hotelparser` user must own or have write access to `uploads` and `outputs`, but
should not have administrative privileges.

Enable and inspect the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hotel-parser
sudo systemctl status hotel-parser
sudo journalctl -u hotel-parser -f
```

### Nginx HTTPS proxy example

Replace `contracts.example.com` with the real domain after its DNS record points to
the server:

```nginx
server {
    listen 80;
    server_name contracts.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name contracts.example.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privatekey.pem;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 600s;
    }
}
```

Use an organization-approved TLS certificate process. Test the Nginx configuration
before reloading it. Long OCR operations may require the extended proxy timeout shown.

## 8. Windows cloud server example

Install Python, Poppler, and Tesseract. Create the virtual environment and install
`requirements.txt` as described in the Windows section.

Set permanent secrets through the Windows service manager or the cloud provider's
secret settings. For a temporary test session only:

```powershell
$env:APP_USERNAME = "contracts-admin"
$env:APP_PASSWORD = "REPLACE_WITH_A_LONG_UNIQUE_PASSWORD"
$env:APP_SECRET_KEY = "REPLACE_WITH_A_RANDOM_SECRET"
$env:APP_HTTPS = "true"
python -m waitress --host=127.0.0.1 --port=8081 --threads=4 web_interface:app
```

Use IIS, a managed load balancer, or another approved reverse proxy for public HTTPS.
The public firewall should permit 443, while port 8081 remains private/localhost-only.
Configure Waitress as a Windows service so it restarts after server reboots.

## 9. Managed cloud platforms and containers

Before choosing a platform, confirm it supports:

- A long-running Python web process
- Poppler and Tesseract system packages or a custom container image
- Requests lasting long enough for OCR processing
- At least 16 MB request bodies (the app upload limit is 16 MB)
- Persistent storage or external object/database storage
- HTTPS and secret environment variables
- Backups and log access

Many managed platforms use an ephemeral filesystem. If `uploads` and `outputs` remain
on ephemeral disk, contracts will disappear during restart, redeployment, or scaling.
Attach persistent storage at those paths or modify the application to use managed
object storage before production use. Multiple application instances cannot safely
share the current local-folder design without shared storage and coordination.

## 10. Data protection and Git

The `uploads` and `outputs` directories contain contract PDFs, rates, generated CSVs,
and metadata. Treat them as confidential business records.

- Do not commit new contract data to Git.
- Review the repository and its history before making it public or adding outsiders.
- Restrict filesystem and backup access to authorized staff.
- Encrypt cloud disks and backups.
- Define a retention period for old uploads and output files.
- Test restoration from backups, not only backup creation.

The repository has previously tracked files in these directories. Adding a path to
`.gitignore` does not remove files already present in Git history. Back up business
data and use a carefully reviewed repository-history cleanup if removal is required.

## 11. Pre-launch checklist

- [ ] Production username, password, and secret key are set outside Git
- [ ] HTTPS works and HTTP redirects to HTTPS for cloud access
- [ ] Port 8081 is not publicly reachable in cloud deployment
- [ ] Poppler and Tesseract verification commands succeed
- [ ] Upload, OCR, manual entry, library, download, reload, and delete are tested
- [ ] `uploads` and `outputs` use persistent storage
- [ ] Automated backups exist and a restoration test has succeeded
- [ ] Disk, CPU, memory, service health, and logs are monitored
- [ ] The service automatically restarts after a server reboot
- [ ] Only authorized users know the credentials
- [ ] A password-rotation and staff-access-removal process is defined
- [ ] The repository contains no new confidential documents or secrets

## 12. Updating the application safely

1. Back up `uploads` and `outputs`.
2. Test the new commit in a separate environment.
3. Pull or deploy the approved commit.
4. Activate the virtual environment and run:

   ```text
   python -m pip install -r requirements.txt
   ```

5. Restart Waitress or the operating-system service.
6. Repeat the functional tests in the pre-launch checklist.
7. Roll back to the previous tested commit if critical checks fail.

Change passwords/secrets separately from ordinary code updates. Rotate them immediately
after suspected disclosure; otherwise follow the organization's normal rotation policy.

## 13. Current authentication limitation

The current application uses one shared HTTP Basic username and password. HTTPS makes
transport secure, but individual users cannot be identified separately. For a larger
team or stronger audit requirements, add individual accounts, roles, login throttling,
password-reset procedures, and records showing who changed or deleted each contract.
