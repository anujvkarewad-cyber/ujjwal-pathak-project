"""Offline notes preparation: PDF integrity, auth, bounds, fallback, isolation."""
import io
import json
import subprocess
from unittest.mock import Mock

import pikepdf
import pytest
from PIL import Image, ImageDraw

from note_pdf_optimizer import optimize_pdf
from routers import note_compression as route


def pdf_fixture(image=True, form=False, encrypted=False, small=False):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(595, 842))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    content = b'BT /F1 16 Tf 40 780 Td (GST Section 16 - readable searchable text) Tj ET\n'
    if image:
        width, height = (100, 100) if small else (900, 1200)
        im = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(im)
        for y in range(20, height - 20, 32):
            draw.text((20, y), 'Study notes: 12.5% tax; A + B = C; section 16(2)', fill='black')
        stream = pikepdf.Stream(pdf, im.tobytes())
        stream.Type = pikepdf.Name.XObject
        stream.Subtype = pikepdf.Name.Image
        stream.Width, stream.Height = width, height
        stream.ColorSpace = pikepdf.Name.DeviceRGB
        stream.BitsPerComponent = 8
        page.Resources.XObject = pikepdf.Dictionary(Scan=stream)
        content += b'q 480 0 0 640 40 80 cm /Scan Do Q\n'
    page.Contents = pikepdf.Stream(pdf, content)
    page.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
        Subtype=pikepdf.Name.Link, Rect=[40, 740, 250, 765], A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.test/chapter')))])
    if form:
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([]))
    dest = io.BytesIO()
    kwargs = {'compress_streams': False}
    if encrypted:
        kwargs['encryption'] = pikepdf.Encryption(owner='owner-test', user='reader-test')
    pdf.save(dest, **kwargs)
    pdf.close()
    return dest.getvalue()


def test_scan_compresses_without_changing_text_links_or_resolution():
    source = pdf_fixture()
    result, report = optimize_pdf(source)
    assert report['status'] == 'compressed'
    assert report['imagesOptimized'] == 1
    assert len(result) < len(source) * .8
    with pikepdf.open(io.BytesIO(source)) as before, pikepdf.open(io.BytesIO(result)) as after:
        assert len(after.pages) == 1
        assert before.pages[0].Contents.read_bytes() == after.pages[0].Contents.read_bytes()
        assert str(after.pages[0].Annots[0].A.URI) == 'https://example.test/chapter'
        im = after.pages[0].Resources.XObject.Scan
        assert (int(im.Width), int(im.Height)) == (900, 1200)
        assert len(pikepdf.PdfImage(im).as_pil_image().tobytes()) == 900 * 1200 * 3


def test_searchable_text_survives_with_independent_parser():
    pypdf = pytest.importorskip('pypdf')  # verification-only dependency
    before = pdf_fixture()
    after, _ = optimize_pdf(before)
    assert pypdf.PdfReader(io.BytesIO(before)).pages[0].extract_text() == pypdf.PdfReader(io.BytesIO(after)).pages[0].extract_text()


@pytest.mark.parametrize('kwargs,reason', [({'form': True}, 'forms_or_signatures'), ({'encrypted': True}, 'encrypted_pdf')])
def test_sensitive_pdf_original_is_byte_identical(kwargs, reason):
    source = pdf_fixture(**kwargs)
    result, report = optimize_pdf(source)
    assert result == source and report['reason'] == reason


def test_explicit_signature_without_form_is_preserved():
    with pikepdf.open(io.BytesIO(pdf_fixture())) as pdf:
        pdf.Root.Perms = pikepdf.Dictionary()
        out = io.BytesIO(); pdf.save(out)
    source = out.getvalue()
    result, report = optimize_pdf(source)
    assert result == source and report['reason'] == 'forms_or_signatures'


def test_invalid_pdf_falls_back_without_leaking_content():
    for data in [b'not a pdf private content', b'%PDF-1.7\nprivate truncated content']:
        result, report = optimize_pdf(data)
        assert result == data
        assert report['status'] == 'original'
        assert 'private' not in json.dumps(report)


def test_efficient_text_pdf_is_not_enlarged():
    source = pdf_fixture(image=False)
    result, report = optimize_pdf(source)
    assert len(result) <= len(source)
    assert report['status'] == 'original'
    assert result == source


def test_repeat_balanced_never_enlarges_output():
    one, _ = optimize_pdf(pdf_fixture())
    two, _ = optimize_pdf(one)
    assert len(two) <= len(one)


def test_complex_mask_image_is_not_reencoded():
    with pikepdf.open(io.BytesIO(pdf_fixture())) as pdf:
        pdf.pages[0].Resources.XObject.Scan.Mask = pikepdf.Array([0, 0, 0, 0, 0, 0])
        out = io.BytesIO(); pdf.save(out, compress_streams=False)
    result, report = optimize_pdf(out.getvalue())
    assert report['imagesOptimized'] == 0
    with pikepdf.open(io.BytesIO(result)) as pdf:
        assert '/Mask' in pdf.pages[0].Resources.XObject.Scan


def test_small_diagram_not_lossily_reencoded():
    result, report = optimize_pdf(pdf_fixture(small=True))
    assert report['imagesOptimized'] == 0


def test_image_budget_skips_oversized_image(monkeypatch):
    import note_pdf_optimizer as optimizer
    monkeypatch.setattr(optimizer, 'MAX_IMAGE_PIXELS', 100)
    _, report = optimizer.optimize_pdf(pdf_fixture())
    assert report['imagesOptimized'] == 0


def test_page_budget_preserves_original(monkeypatch):
    import note_pdf_optimizer as optimizer
    monkeypatch.setattr(optimizer, 'MAX_PAGES', 0)
    source = pdf_fixture(image=False)
    assert optimizer.optimize_pdf(source)[0] == source


def test_bounded_worker_real_execution():
    source = pdf_fixture()
    result, report = route.optimize_bounded(source)
    assert report['status'] == 'compressed' and len(result) < len(source)


@pytest.mark.parametrize('exception,reason', [(subprocess.TimeoutExpired('worker', 25), 'processing_timeout'), (subprocess.CalledProcessError(1, 'worker'), 'processing_failed')])
def test_worker_failure_returns_original_and_removes_temp_files(monkeypatch, exception, reason):
    parents = []
    def failing(args, **kwargs):
        from pathlib import Path
        parents.append(Path(args[2]).parent)
        raise exception
    monkeypatch.setattr(route.subprocess, 'run', failing)
    source = pdf_fixture(image=False)
    result, report = route.optimize_bounded(source)
    assert result == source and report['reason'] == reason
    assert all(not p.exists() for p in parents)


def test_unauthenticated_prepare_never_runs_optimizer(client, monkeypatch):
    worker = Mock(); monkeypatch.setattr(route, 'optimize_bounded', worker)
    res = client.post('/api/mentor/notes/prepare', content=b'%PDF-1.7', headers={'Content-Type': 'application/pdf'})
    assert res.status_code == 401
    worker.assert_not_called()


def test_original_endpoint_exact_bytes_and_private_headers(client, mentor_headers, monkeypatch):
    worker = Mock(); monkeypatch.setattr(route, 'optimize_bounded', worker)
    source = pdf_fixture()
    res = client.post('/api/mentor/notes/prepare?quality=original', content=source, headers={**mentor_headers, 'Content-Type': 'application/pdf'})
    assert res.status_code == 200 and res.content == source
    assert res.headers['x-notes-status'] == 'original'
    assert res.headers['cache-control'] == 'no-store'
    assert res.headers['x-content-type-options'] == 'nosniff'
    worker.assert_not_called()


def test_balanced_endpoint_size_headers(client, mentor_headers):
    source = pdf_fixture()
    res = client.post('/api/mentor/notes/prepare', content=source, headers={**mentor_headers, 'Content-Type': 'application/pdf'})
    assert res.status_code == 200 and res.headers['x-notes-status'] == 'compressed'
    assert int(res.headers['x-notes-original-bytes']) == len(source)
    assert int(res.headers['x-notes-output-bytes']) == len(res.content)
    assert len(res.content) < len(source)


@pytest.mark.parametrize('url,body,kind,status', [
    ('?quality=smallest', b'%PDF-1.7', 'application/pdf', 400),
    ('', b'%PDF-1.7', 'image/png', 415),
    ('', b'', 'application/pdf', 400),
    ('', b'<html>not pdf</html>', 'application/pdf', 400),
])
def test_bad_requests_rejected(client, mentor_headers, url, body, kind, status):
    res = client.post('/api/mentor/notes/prepare' + url, content=body, headers={**mentor_headers, 'Content-Type': kind})
    assert res.status_code == status


def test_limit_and_busy_fail_closed(client, mentor_headers, monkeypatch):
    headers = {**mentor_headers, 'Content-Type': 'application/pdf'}
    monkeypatch.setattr(route, 'MAX_BYTES', 20)
    res = client.post('/api/mentor/notes/prepare', content=b'%PDF-' + b'a' * 50, headers=headers)
    assert res.status_code == 413
    assert route._SLOT.acquire(False)
    try:
        res = client.post('/api/mentor/notes/prepare', content=b'%PDF-1.7', headers=headers)
        assert res.status_code == 429 and res.headers['retry-after'] == '5'
    finally:
        route._SLOT.release()


def test_streamed_limit_cannot_be_bypassed_without_content_length(client, mentor_headers, monkeypatch):
    monkeypatch.setattr(route, 'MAX_BYTES', 20)
    res = client.post('/api/mentor/notes/prepare', content=iter([b'%PDF-1.7', b'x' * 21]), headers={**mentor_headers, 'Content-Type': 'application/pdf'})
    assert res.status_code == 413


def test_slot_released_after_invalid_input(client, mentor_headers):
    client.post('/api/mentor/notes/prepare', content=b'bad', headers={**mentor_headers, 'Content-Type': 'application/pdf'})
    assert route._SLOT.acquire(False)
    route._SLOT.release()


def test_internal_destinations_bookmarks_and_metadata_survive():
    with pikepdf.open(io.BytesIO(pdf_fixture())) as pdf:
        second = pdf.add_blank_page(page_size=(595, 842))
        pdf.pages[0].Annots.append(pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[1, 1, 10, 10],
            Dest=pikepdf.Array([second.obj, pikepdf.Name.Fit]))))
        with pdf.open_outline() as outline:
            outline.root.append(pikepdf.OutlineItem('Chapter two', 1))
        pdf.docinfo['/Title'] = 'CA notes verification'
        buffer = io.BytesIO(); pdf.save(buffer, compress_streams=False)
    result, report = optimize_pdf(buffer.getvalue())
    assert report['status'] == 'compressed'
    with pikepdf.open(io.BytesIO(result)) as pdf:
        assert len(pdf.pages) == 2
        assert pdf.pages[0].Annots[1].Dest[0].objgen == pdf.pages[1].obj.objgen
        assert pdf.docinfo['/Title'] == 'CA notes verification'
        with pdf.open_outline() as outline:
            assert outline.root[0].title == 'Chapter two'
            assert outline.root[0].destination[0].objgen == pdf.pages[1].obj.objgen
