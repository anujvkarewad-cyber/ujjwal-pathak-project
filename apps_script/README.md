# Google Apps Script Backend Setup

This folder contains the full Apps Script backend that connects your dashboard
to your live Google Sheet. Follow these steps once.

## 1 · Open the script editor
1. Open your sheet: <https://docs.google.com/spreadsheets/d/1oYYodP_XcbJOjrP5c4PirQDCnl54NFyPUbf7lwM1Ycc/edit>
2. In the top menu click **Extensions → Apps Script**.
3. A new tab opens with a file called `Code.gs` (may be empty or have a `function myFunction()` placeholder). **Select all → delete**.

## 2 · Paste the code
1. Open [`Code.gs`](./Code.gs) in this repo.
2. **Copy everything** and paste it into the Apps Script editor.
3. Press **Ctrl + S** (or ⌘ + S). Give the project a name like *Mentor Dashboard API*.

## 3 · Run `setupSheets` (one time)
1. In the toolbar dropdown next to the ▶ Run button, choose **`setupSheets`**.
2. Click **Run**.
3. Google will show *"Authorization required"* → click **Review permissions** → choose your Google account → **Advanced → Go to <script name> (unsafe)** → **Allow**.
   (This is normal — you are authorising *your own script* to edit *your own sheet*.)
4. When it finishes you should see in the execution log:
   `Setup complete. N students in master.`

This creates all missing tabs (`Students`, `Announcements`, `MentorNotes`,
`Mentor`, `Notifications`, `MCQ`, `Attendance`) and pre-fills your students
based on unique IDs found in `Form responses 1`.

## 4 · Deploy as a Web App
1. Top-right → **Deploy → New deployment**.
2. Click the ⚙ gear icon → select **Web app**.
3. Fill in:
   - **Description**: `Mentor Dashboard API v1`
   - **Execute as**: `Me (<your email>)`
   - **Who has access**: `Anyone`
4. Click **Deploy**. Grant permission again if prompted.
5. Copy the **Web app URL** (ends in `/exec`). It looks like:
   `https://script.google.com/macros/s/AKfycb.../exec`

## 5 · Send the URL to the developer
Paste it back in chat and I will wire it into the frontend.

You are done. Any daily-tracker form submission afterwards will show up on the
dashboard on next refresh.

## 6 · Filling in the auto-created tabs (optional)
- **Students** — pre-filled from unique IDs. Add real `name`, `email`, `phone`, `avatar`, `batch`, `attempt`, `group`, `level`, `city` to make the dashboard richer.
- **MCQ** — add rows like `date, studentId, mcqCount, mcqAccuracy` when you run mock tests.
- **Attendance** — `date, studentId, present (true/false)` if you want a separate attendance signal.
- **Announcements** — you can also create these from the dashboard UI (Announcements page) — they get written straight to this sheet.

## Re-deploying after code changes
If you paste an updated `Code.gs`:
1. **Save** (⌘ + S).
2. **Deploy → Manage deployments** → your existing web-app → ✏ Edit → **Version: New version** → **Deploy**.
3. URL stays the same. No need to update the frontend.
