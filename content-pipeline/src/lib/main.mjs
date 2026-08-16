// Executed-as-CLI detection for stage modules, so tests can import stages
// without triggering their auto-run.
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export function isMain(metaUrl) {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    return metaUrl === pathToFileURL(path.resolve(entry)).href;
  } catch {
    return false;
  }
}
