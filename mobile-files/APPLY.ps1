$ErrorActionPreference = "Stop"
Write-Host "Downloading OTA-only patch (MCQ sync already in your repo)..." -ForegroundColor Cyan
Invoke-WebRequest "https://raw.githubusercontent.com/anujvkarewad-cyber/ujjwal-pathak-project/arena/01a01518-ujjwal-pathak-project/mobile-files/mobile/OTA-FIX.patch" -OutFile "OTA-FIX.patch"
git fetch origin
Write-Host "Applying OTA patch on top of your current code..." -ForegroundColor Cyan
git apply "OTA-FIX.patch"
if ($LASTEXITCODE -ne 0) { Write-Host "Apply FAILED - paste output." -ForegroundColor Red; exit 1 }
Write-Host "Committing + pushing..." -ForegroundColor Cyan
git add mobile/
git commit -m "Enable OTA updates (expo-updates) + show sharing toggle in all modes"
git push origin main
Write-Host "DONE!" -ForegroundColor Green
