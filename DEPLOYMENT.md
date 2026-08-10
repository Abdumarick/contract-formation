# Office deployment checklist

## Before launch

1. Confirm the Windows network profile is **Private**, not Public.
2. Install the production server:
   `.venv\Scripts\pip install -r requirements.txt`
3. Run `run_web.bat` and enter a strong, unique username and password.
4. Run `ipconfig` and give staff the server's IPv4 address, for example
   `http://192.168.1.20:8081`.
5. If Windows Firewall prompts, allow TCP port 8081 on **Private networks only**.
6. Test upload, manual entry, library download, reload, and delete from a second PC.
7. Arrange backups for the `uploads` and `outputs` folders.

## Important security limits

This setup is intended only for a trusted office LAN. HTTP Basic authentication over
plain HTTP does not encrypt passwords or contract data. Do not expose port 8081 to
the internet, forward it on the router, or make it available to guest Wi-Fi.

For remote use or untrusted networks, place the application behind HTTPS and an
organization-managed VPN or reverse proxy. Use a valid TLS certificate.

The repository currently contains tracked files under `uploads` and `outputs`.
These can contain confidential contracts and rates. Before pushing the repository to
GitHub or another remote, remove those data files from Git tracking and review the
repository history. Back up the folders before any cleanup.

## Operations

- Keep the host computer awake and connected to the office network.
- Stop the service with Ctrl+C in its console.
- Restart it after Windows updates or application changes.
- Do not share the office password outside the authorized team.
- Change the password if a staff member who knew it leaves the team.
