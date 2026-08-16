// Central configuration for the content pipeline.
// Loads .env (gitignored) — never hardcode secrets.
import 'dotenv/config';
import path from 'node:path';
import fs from 'node:fs';

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname);

const int = (v, dflt) => {
  const n = Number.parseInt(v ?? '', 10);
  return Number.isFinite(n) ? n : dflt;
};
const flt = (v, dflt) => {
  const n = Number.parseFloat(v ?? '');
  return Number.isFinite(n) ? n : dflt;
};

export const config = {
  root: ROOT,

  // AI provider
  aiProvider: process.env.AI_PROVIDER || 'openai',
  openai: {
    apiKey: process.env.OPENAI_API_KEY || '',
    baseUrl: process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1',
    model: process.env.OPENAI_MODEL || 'gpt-4o',
  },
  anthropic: {
    apiKey: process.env.ANTHROPIC_API_KEY || '',
    model: process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-20250514',
  },
  gemini: {
    apiKey: process.env.GEMINI_API_KEY || '',
    model: process.env.GEMINI_MODEL || 'gemini-2.0-flash',
  },

  // Google Drive
  googleCredentialsPath: process.env.GOOGLE_APPLICATION_CREDENTIALS || './secrets/service-account.json',
  driveFolders: {
    modules: process.env.DRIVE_FOLDER_MODULES || '',
    rtp: process.env.DRIVE_FOLDER_RTP || '',
    mtp: process.env.DRIVE_FOLDER_MTP || '',
    pyq: process.env.DRIVE_FOLDER_PYQ || '',
  },

  // Storage
  mongoUrl: process.env.MONGO_URL || 'mongodb://localhost:27017',
  dbName: process.env.DB_NAME || 'ujjwal_pathak',
  memoryDbFile: process.env.MEMORY_DB_FILE || '',

  // Paths
  cacheDir: path.resolve(ROOT, process.env.PIPELINE_CACHE_DIR || '.cache/drive'),
  stateDir: path.resolve(ROOT, process.env.PIPELINE_STATE_DIR || 'state'),
  distDir: path.resolve(ROOT, process.env.PIPELINE_DIST_DIR || 'dist'),

  // Catalog authority
  studentRepoPath: process.env.STUDENT_REPO_PATH || '',
  catalogSnapshotPath: path.resolve(ROOT, process.env.CATALOG_SNAPSHOT_PATH || 'config/chapters.json'),
  expectedChapterCount: int(process.env.EXPECTED_CHAPTER_COUNT, 94),

  // Generation
  questionsPlainPerChapter: int(process.env.QUESTIONS_PLAIN_PER_CHAPTER, 30),
  scenariosPerChapter: int(process.env.SCENARIOS_PER_CHAPTER, 5),
  questionsPerScenario: int(process.env.QUESTIONS_PER_SCENARIO, 4),
  generationParallelism: int(process.env.GENERATION_PARALLELISM, 2),
  generationMaxRetries: int(process.env.GENERATION_MAX_RETRIES, 3),

  // Similarity gates
  similarityFlag: flt(process.env.SIMILARITY_FLAG, 0.75),
  similarityBlock: flt(process.env.SIMILARITY_BLOCK, 0.9),

  // Publishing
  publicContentBaseUrl: process.env.PUBLIC_CONTENT_BASE_URL || 'http://localhost:8000/api/content/student',
};

export function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
  return p;
}

// Named "exit points" so every stage fails closed the same way.
export class PipelineError extends Error {
  constructor(message, { stage, chapterId = null, details = null } = {}) {
    super(message);
    this.name = 'PipelineError';
    this.stage = stage;
    this.chapterId = chapterId;
    this.details = details;
  }
}

export function fail(stage, message, extra = {}) {
  throw new PipelineError(message, { stage, ...extra });
}
