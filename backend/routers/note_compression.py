"""Mentor-only prepare/preview endpoint; never publishes or sends notifications."""
import asyncio
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from auth import require_mentor
from note_pdf_optimizer import MAX_BYTES

router = APIRouter(prefix='/api/mentor/notes', tags=['mentor-note-preparation'])
_SLOT = threading.BoundedSemaphore(1)
WORKER_TIMEOUT = 25
BACKEND_DIR = Path(__file__).resolve().parent.parent
EXPOSE_HEADERS = 'X-Notes-Status, X-Notes-Reason, X-Notes-Original-Bytes, X-Notes-Output-Bytes, X-Notes-Images'


def optimize_bounded(data):
    fallback = {'status': 'original', 'reason': 'processing_failed', 'imagesOptimized': 0}
    with tempfile.TemporaryDirectory(prefix='upm-note-') as folder:
        source, output, meta = [Path(folder) / name for name in ('input.pdf', 'output.pdf', 'result.json')]
        source.write_bytes(data)
        source.chmod(0o600)
        try:
            subprocess.run([sys.executable, str(BACKEND_DIR / 'note_pdf_worker.py'), str(source), str(output), str(meta)],
                           cwd=str(BACKEND_DIR), timeout=WORKER_TIMEOUT, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if output.stat().st_size > len(data):
                return data, fallback
            selected, report = output.read_bytes(), json.loads(meta.read_text())
            if report.get('status') not in {'original', 'compressed'} or not selected.lstrip().startswith(b'%PDF-'):
                return data, fallback
            if report['status'] == 'original':
                return data, report  # exact bytes, even if worker wrote something else
            return selected, report
        except subprocess.TimeoutExpired:
            return data, {**fallback, 'reason': 'processing_timeout'}
        except (OSError, ValueError, subprocess.CalledProcessError):
            return data, fallback


async def read_limited(request):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, 'Notes preparation supports PDFs up to 20 MB.')
        chunks.extend(chunk)
    if not chunks or not chunks.lstrip().startswith(b'%PDF-'):
        raise HTTPException(400, 'Choose a PDF file with a valid PDF header.')
    return bytes(chunks)


@router.post('/prepare')
async def prepare_note(request: Request, quality: str = 'balanced', mentor=Depends(require_mentor)):
    if quality not in {'balanced', 'original'}:
        raise HTTPException(400, 'Choose balanced or original quality.')
    if request.headers.get('content-type', '').split(';')[0].lower() != 'application/pdf':
        raise HTTPException(415, 'This notes uploader accepts PDF files only.')
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) < 0 or int(length) > MAX_BYTES:
                raise HTTPException(413, 'Notes preparation supports PDFs up to 20 MB.')
        except ValueError:
            raise HTTPException(400, 'Invalid content length.')
    if not _SLOT.acquire(blocking=False):
        raise HTTPException(429, 'Another PDF is being prepared. Try again or use Original quality.', headers={'Retry-After': '5'})
    try:
        try:
            data = await asyncio.wait_for(read_limited(request), timeout=60)
        except asyncio.TimeoutError:
            raise HTTPException(408, 'PDF transfer timed out. Retry or use Original quality.')
        if quality == 'original':
            selected, report = data, {'status': 'original', 'reason': 'original_selected', 'imagesOptimized': 0}
        else:
            selected, report = await run_in_threadpool(optimize_bounded, data)
        return Response(selected, media_type='application/pdf', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'inline; filename="prepared-note.pdf"',
            'Access-Control-Expose-Headers': EXPOSE_HEADERS,
            'X-Notes-Status': report['status'], 'X-Notes-Reason': report['reason'],
            'X-Notes-Original-Bytes': str(len(data)), 'X-Notes-Output-Bytes': str(len(selected)),
            'X-Notes-Images': str(report.get('imagesOptimized', 0)),
        })
    finally:
        _SLOT.release()
