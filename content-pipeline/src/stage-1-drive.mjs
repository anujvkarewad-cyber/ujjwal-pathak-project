// Stage 1 — Google Drive sync + cache.
// Downloads every file under the configured folder IDs (Modules, RTP, MTP, PYQ)
// into .cache/drive/<kind>/... and records sha256 + mtime so unchanged files
// are never re-downloaded. Fails closed when credentials or folder IDs are
// missing — a chapter with an incomplete source set is blocked downstream.

import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { google } from 'googleapis';
import { config, ensureDir, fail } from './lib/config.mjs';
import { isMain } from './lib/main.mjs';

const KINDS = ['modules', 'rtp', 'mtp', 'pyq'];
const MIME_TEXT = new Set(['text/plain', 'text/markdown', 'application/json']);

function sha256(buf) {
  return createHash('sha256').update(buf).digest('hex');
}

async function listAll(drive, folderId) {
  const files = [];
  let pageToken = null;
  do {
    const res = await drive.files.list({
      q: `'${folderId}' in parents and trashed = false`,
      fields: 'nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)',
      pageSize: 1000,
      pageToken: pageToken || undefined,
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    });
    for (const f of res.data.files || []) {
      files.push(f);
      if (f.mimeType === 'application/vnd.google-apps.folder') {
        files.push(...(await listAll(drive, f.id)));
      }
    }
    pageToken = res.data.nextPageToken;
  } while (pageToken);
  return files;
}

async function download(drive, file, destDir) {
  const res = await drive.files.get(
    { fileId: file.id, alt: 'media' },
    { responseType: 'stream' }
  );
  const target = path.join(destDir, sanitize(file.name));
  const tmp = `${target}.part`;
  await new Promise((resolve, reject) => {
    const ws = fs.createWriteStream(tmp);
    res.data
      .on('error', reject)
      .pipe(ws)
      .on('finish', resolve)
      .on('error', reject);
  });
  fs.renameSync(tmp, target);
  const buf = fs.readFileSync(target);
  return { path: target, sha256: sha256(buf), size: buf.length };
}

function sanitize(name) {
  return String(name).replace(/[^\w.\-() ]+/g, '_').slice(0, 180);
}

export async function main() {
  console.log('[stage-1] drive sync');
  const credPath = path.resolve(config.root, config.googleCredentialsPath);
  if (!fs.existsSync(credPath)) {
    fail('drive', `Google service-account file not found: ${credPath} (set GOOGLE_APPLICATION_CREDENTIALS)`);
  }
  const auth = new google.auth.GoogleAuth({
    keyFile: credPath,
    scopes: ['https://www.googleapis.com/auth/drive.readonly'],
  });
  const drive = google.drive({ version: 'v3', auth });

  const manifestPath = path.join(config.cacheDir, 'manifest.json');
  const manifest = fs.existsSync(manifestPath)
    ? JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    : { files: {} };

  const stats = { downloaded: 0, skipped: 0 };
  for (const kind of KINDS) {
    const folderId = config.driveFolders[kind];
    if (!folderId) {
      if (kind === 'modules') {
        fail('drive', 'DRIVE_FOLDER_MODULES is not set — refusing partial source set (modules are mandatory).');
      }
      console.warn(
        `[stage-1] DRIVE_FOLDER_${kind.toUpperCase()} not set — skipping ${kind}. ` +
          `Calibration sources are optional here; questions without RTP/MTP/PYQ calibration refs ` +
          `will still be blocked later by content validation (stage-7).`
      );
      continue;
    }
    const destDir = ensureDir(path.join(config.cacheDir, kind));
    const files = await listAll(drive, folderId);
    console.log(`[stage-1] ${kind}: ${files.length} files in Drive`);

    for (const file of files) {
      const md5 = file.md5Checksum || file.modifiedTime;
      const cached = manifest.files[file.id];
      if (cached && cached.md5 === md5 && fs.existsSync(cached.path)) {
        stats.skipped++;
        continue;
      }
      const { path: p, sha256: h, size } = await download(drive, file, destDir);
      manifest.files[file.id] = {
        id: file.id,
        kind,
        name: file.name,
        path: path.relative(config.root, p),
        md5,
        modifiedTime: file.modifiedTime,
        sha256: h,
        size,
        downloadedAt: new Date().toISOString(),
      };
      stats.downloaded++;
    }
  }

  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  console.log(`[stage-1] OK — downloaded ${stats.downloaded}, skipped ${stats.skipped} unchanged`);
}

if (isMain(import.meta.url)) {
  main().catch((err) => {
    console.error(`[stage-1] FAILED: ${err.message}`);
    process.exit(1);
  });
}
