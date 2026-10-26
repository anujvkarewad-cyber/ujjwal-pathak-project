"""Conservative mentor-notes PDF optimizer. No database, Drive or network access.

Text/page drawing streams are never rasterized. Eligible 8-bit RGB/gray image
XObjects retain pixel dimensions; only their encoding may become JPEG quality 90.
This is not a PDF sanitizer. Complex/encrypted/form/signed documents keep bytes.
"""
import hashlib
import io

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 400
MAX_IMAGE_PIXELS = 12_000_000
MAX_TOTAL_IMAGE_PIXELS = 40_000_000


def _page_signature(pdf):
    result = []
    for page in pdf.pages:
        contents = page.obj.get('/Contents')
        if contents is None:
            streams = []
        elif hasattr(contents, 'read_bytes'):
            streams = [contents]
        else:
            streams = list(contents)
        hashes = [hashlib.sha256(s.read_bytes()).hexdigest() for s in streams]
        links = []
        for annotation in page.obj.get('/Annots', []):
            action = annotation.get('/A', {})
            links.append((str(annotation.get('/Subtype', '')), str(annotation.get('/Rect', '')),
                          str(action.get('/S', '')), str(action.get('/URI', ''))))
        result.append((str(page.mediabox), str(page.obj.get('/CropBox', '')),
                       str(page.obj.get('/Rotate', 0)), hashes, links))
    return result


def optimize_pdf(data):
    """Return (selected bytes, status metadata); any failure returns original."""
    def original(reason):
        return data, {'status': 'original', 'reason': reason, 'imagesOptimized': 0}
    if len(data) > MAX_BYTES:
        return original('size_limit')
    if not data.lstrip().startswith(b'%PDF-'):
        return original('invalid_pdf')
    try:
        import pikepdf
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with pikepdf.open(io.BytesIO(data), attempt_recovery=False) as pdf:
            if pdf.is_encrypted:
                return original('encrypted_pdf')
            if not 0 < len(pdf.pages) <= MAX_PAGES:
                return original('page_limit')
            if '/AcroForm' in pdf.Root or '/Perms' in pdf.Root:
                return original('forms_or_signatures')
            # Includes signatures not attached to a conventional AcroForm.
            for obj in pdf.objects:
                if isinstance(obj, pikepdf.Dictionary) and ('/ByteRange' in obj or obj.get('/Type') == pikepdf.Name('/Sig')):
                    return original('forms_or_signatures')
            signature = _page_signature(pdf)
            pixels = 0
            optimized = 0
            for obj in pdf.objects:
                if not isinstance(obj, pikepdf.Stream) or obj.get('/Subtype') != pikepdf.Name('/Image'):
                    continue
                if any(key in obj for key in ('/SMask', '/Mask', '/Decode', '/Alternates', '/OPI')) or obj.get('/ImageMask', False):
                    continue
                if str(obj.get('/ColorSpace')) not in ('/DeviceRGB', '/DeviceGray') or int(obj.get('/BitsPerComponent', 0)) != 8:
                    continue
                if str(obj.get('/Filter', '')) not in ('/FlateDecode', '/DCTDecode', ''):
                    continue
                width, height = int(obj.get('/Width', 0)), int(obj.get('/Height', 0))
                size = width * height
                if width <= 0 or height <= 0 or size > MAX_IMAGE_PIXELS or pixels + size > MAX_TOTAL_IMAGE_PIXELS:
                    continue
                pixels += size
                if size < 250_000:
                    continue  # leave small diagrams/icons alone
                old_size = len(obj.read_raw_bytes())
                image = pikepdf.PdfImage(obj).as_pil_image()
                if image.mode not in ('RGB', 'L') or image.size != (width, height):
                    continue
                with image:
                    buffer = io.BytesIO()
                    image.save(buffer, format='JPEG', quality=90, subsampling=0, optimize=True)
                    encoded = buffer.getvalue()
                if len(encoded) + 1024 >= old_size * 0.95:
                    continue
                obj.write(encoded, filter=pikepdf.Name('/DCTDecode'))
                if '/DecodeParms' in obj:
                    del obj['/DecodeParms']
                optimized += 1
            output = io.BytesIO()
            pdf.save(output, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                     recompress_flate=True, linearize=False)
            candidate = output.getvalue()
            if len(candidate) > MAX_BYTES or len(data) - len(candidate) < max(1024, len(data) * 0.03):
                return original('no_meaningful_saving')
            with pikepdf.open(io.BytesIO(candidate), attempt_recovery=False) as checked:
                if _page_signature(checked) != signature:
                    return original('verification_failed')
            return candidate, {'status': 'compressed', 'reason': 'optimized', 'imagesOptimized': optimized}
    except ImportError:
        return original('optimizer_unavailable')
    except Exception as exc:
        # Never return exception text: it may contain content from a private PDF.
        if type(exc).__name__ == 'PasswordError':
            return original('encrypted_pdf')
        return original('processing_failed')
