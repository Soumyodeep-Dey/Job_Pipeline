# Phase 9.2 — One active résumé

Open Résumé library to see the active PDF. Place the replacement PDF in the resume folder, then choose **Delete active résumé and scan for replacement**. Confirm the filename before deleting. The app selects the newest valid PDF by modification time, breaking ties by filename. It skips deleted fingerprints and invalid files. If no replacement qualifies, upload a PDF or scan again later. Uploading a different PDF while one is active returns HTTP 409.

Deletion removes a résumé from active use. The original file and database version are retained for past application receipts and audit history. Matching, eligibility and tailored proposals use the active version. A replacement needs a fresh review before use. The configured master initializes existing workspaces. Later choices persist across restarts in migration 0008.

Authenticated endpoints include GET /resumes, DELETE /resumes/{id}, and POST /imports/resumes. Use docker compose up --build -d --wait to upgrade after taking a backup.
