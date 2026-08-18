$ErrorActionPreference = "Stop"
Write-Host "Downloading OTA-only patch (applies cleanly on your repo)..." -ForegroundColor Cyan
Invoke-WebRequest "https://raw.githubusercontent.com/anujvkarewad-cyber/ujjwal-pathak-project/arena/01a01518-ujjwal-pathak-project/mobile-files/mobile/OTA-ONLY.patch" -OutFile "OTA-ONLY.patch"
Write-Host "Applying OTA patch..." -ForegroundColor Cyan
git apply --whitespace=nowarn "OTA-ONLY.patch"
if ($LASTEXITCODE -ne 0) { Write-Host "Apply FAILED - paste output." -ForegroundColor Red; exit 1 }
Write-Host "Committing + pushing..." -ForegroundColor Cyan
git add mobile/
git commit -m "Enable OTA updates (expo-updates)"
git push origin main
Write-Host "DONE! OTA updates enabled." -ForegroundColor Green
