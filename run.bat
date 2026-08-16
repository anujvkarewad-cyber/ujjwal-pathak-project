@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

REM ──────────────────────────────────────────────────────────────
REM CA Inter MCQ Pipeline — run.bat (Windows)
REM Usage: run.bat [ingest|generate|validate|stage|publish|verify|full|test]
REM        run.bat generate --chapter=advanced-accounting-1
REM ──────────────────────────────────────────────────────────────

set ROOT=%~dp0
set PIPELINE_DIR=%ROOT%content-pipeline

if not exist "%PIPELINE_DIR%" (
  echo [ERR] content-pipeline folder not found at %PIPELINE_DIR%
  exit /b 1
)

cd /d "%PIPELINE_DIR%"

set CMD=%1
if "%CMD%"=="" set CMD=help
shift
set EXTRA_ARGS=%*

echo [run.bat] Node check...
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  echo [ERR] Node.js not found. Install Node >=20 from https://nodejs.org
  exit /b 1
)

if not exist ".env" (
  echo [WARN] .env not found
  if exist "%ROOT%.env.example" (
    copy "%ROOT%.env.example" ".env"
    echo Created .env from template — PLEASE EDIT with real keys!
  ) else if exist ".env.example" (
    copy ".env.example" ".env"
  ) else (
    echo [ERR] No .env.example found
    exit /b 1
  )
)

if not exist "secrets\service-account.json" (
  echo [WARN] secrets\service-account.json missing — Drive sync will fail
)

if not exist "node_modules" (
  echo [run.bat] npm install...
  call npm install
  if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)

if /I "%CMD%"=="ingest" goto ingest
if /I "%CMD%"=="generate" goto generate
if /I "%CMD%"=="validate" goto validate
if /I "%CMD%"=="stage" goto stage
if /I "%CMD%"=="publish" goto publish
if /I "%CMD%"=="verify" goto verify
if /I "%CMD%"=="full" goto full
if /I "%CMD%"=="test" goto test
goto help

:ingest
echo --^> Ingest stages 0-4
call npm run stage:catalog
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
call npm run stage:drive
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
call npm run stage:extract
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
call npm run stage:normalize
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
call npm run stage:map
goto done

:generate
echo --^> Generate stage-5 %EXTRA_ARGS%
node src\stage-5-generate.mjs %EXTRA_ARGS%
goto done

:validate
echo --^> Validate 6-9
call npm run stage:validate-schema
call npm run stage:validate-content
call npm run stage:duplicates
call npm run stage:coverage
goto done

:stage
echo --^> Stage to review
call npm run stage:stage
goto done

:publish
echo --^> Publish %EXTRA_ARGS%
node src\stage-11-publish.mjs %EXTRA_ARGS%
node src\stage-12-verify.mjs
goto done

:verify
node src\stage-12-verify.mjs
goto done

:full
echo --^> Full pipeline
call npm run stage:catalog
call npm run stage:drive
call npm run stage:extract
call npm run stage:normalize
call npm run stage:map
node src\stage-5-generate.mjs %EXTRA_ARGS%
call npm run stage:validate-schema
call npm run stage:validate-content
call npm run stage:duplicates
call npm run stage:coverage
call npm run stage:stage
echo Full done. Review dashboard then run.bat publish --chapter=ID
goto done

:test
call npm test
goto done

:help
echo Usage: run.bat ^<command^> [extra args]
echo.
echo Commands:
echo   ingest                 Catalog + Drive + Extract + Normalize + Map
echo   generate [--dry-run] [--chapter=ID]
echo   validate               Schema + content + duplicates + coverage
echo   stage                  Push to mentor review queue
echo   publish --chapter=ID   Publish approved chapter + verify
echo   verify                 Verify bundles
echo   full                   ingest -^> generate -^> validate -^> stage
echo   test                   npm test
echo.
echo Examples:
echo   run.bat ingest
echo   run.bat generate --dry-run
echo   run.bat generate --chapter=advanced-accounting-1
echo   run.bat validate
echo   run.bat full
echo.
echo Setup: see RUNNING.md and RUN_ACTIONS.md
goto done

:done
ENDLOCAL
