# ============================================================
#  UPM student repo — apply MCQ sync fix + push (one click)
#  Run this INSIDE your student-dashboard-frontend folder.
# ============================================================
$ErrorActionPreference = "Stop"

Write-Host "Step 1: Removing the wrong .patch commit from earlier..." -ForegroundColor Cyan
git reset --soft HEAD~1 2>$null
git reset 2>$null

Write-Host "Step 2: Deleting stray .patch files..." -ForegroundColor Cyan
Remove-Item -ErrorAction SilentlyContinue apk.patch, debug.patch, debug2.patch, debug3.patch, debug4.patch, final.patch

Write-Host "Step 3: Downloading the real fix patch..." -ForegroundColor Cyan
Invoke-WebRequest "https://raw.githubusercontent.com/anujvkarewad-cyber/ujjwal-pathak-project/arena/01a01518-ujjwal-pathak-project/mobile-files/mobile/FULL-FIX.patch" -OutFile "FULL-FIX.patch"

Write-Host "Step 4: Syncing with remote main (fetch first to avoid reject)..." -ForegroundColor Cyan
git fetch origin
git reset --hard origin/main

Write-Host "Step 5: Applying the fix..." -ForegroundColor Cyan
git apply "FULL-FIX.patch"
if ($LASTEXITCODE -ne 0) { Write-Host "Apply FAILED - paste output to the agent." -ForegroundColor Red; exit 1 }

Write-Host "Step 6: Committing + pushing..." -ForegroundColor Cyan
git add mobile/
git commit -m "Sync MCQ progress to mentor analytics + fix notification crash"
git push origin main

Write-Host ""
Write-Host "DONE! Check GitHub, it should be pushed." -ForegroundColor Green
