# Calling Veera — Cloud Ready V2

This is the cloud version of the original **Calling Campaign App V1**. It keeps the original calling flow — a CALL button opens the phone dialer — and adds shared cloud features.

## Included
- Caller accounts and login
- Admin accounts, maximum 3
- Caller CSV import: `Name,Username,Password,Phone`
- Lead CSV import: `Name,Phone`
- Assign every lead to every selected caller
- Round-robin assignment option
- Caller mobile dashboard with search/status filters
- CALL button using Android dialer
- WhatsApp button with prefilled message and `{name}` substitution
- Call attempts, statuses, notes and last-called time
- Caller and admin CSV exports
- Admin monitoring by caller
- Render Blueprint with a web service + Postgres database
- `/health` health check

## First login
The first person who opens the deployed site creates the first admin. After that, the setup page is locked.

## Caller CSV
```csv
Name,Username,Password,Phone
Rahul,rahul,StrongPass123,9876543210
Amit,amit,StrongPass456,9123456789
```

## Lead CSV
```csv
Name,Phone
Rahul Kumar,9876543210
Amit Kumar,9123456789
```

## Render
The included `render.yaml` defines the service and database. Render supports Python web services and Blueprints, and the app binds to `0.0.0.0` as required for public web services.

The Blueprint currently selects Render's Free web service and Free Postgres so it can be tested without payment. Render documents that Free Postgres expires after 30 days, so use a paid database for long-term operational data.

## Security notes
- Passwords are hashed before storage.
- Do not commit real caller passwords or lead data to GitHub.
- The repository can contain only application source code; upload CSV data through the admin screen after deployment.
- Change the generated Render secret only through Render environment settings if needed.
