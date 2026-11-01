"""One disposable optimizer process, bounded by parent timeout and OS limits."""
import json
import sys
from pathlib import Path


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
    except ImportError:
        pass  # parent wall timeout/input cap still applies on non-POSIX hosts
    from note_pdf_optimizer import optimize_pdf
    source, target, metadata = map(Path, sys.argv[1:])
    data, report = optimize_pdf(source.read_bytes())
    target.write_bytes(data)
    metadata.write_text(json.dumps(report))


if __name__ == '__main__':
    main()
