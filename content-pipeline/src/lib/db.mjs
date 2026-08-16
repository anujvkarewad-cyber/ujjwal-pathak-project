// Pipeline MongoDB access (stages 10–12). Uses the official `mongodb` driver.
// Content collections are namespaced `content_*` — physically separate from
// analytics namespaces and from anything the existing student backend uses.
//
// MONGO_URL=memory://  → in-memory store implementing the subset of the
//                        Mongo API the pipeline uses (dev/test only).
// Any other MONGO_URL   → real MongoDB via the official driver.

import fs from 'node:fs';
import { MongoClient } from 'mongodb';
import { config } from './config.mjs';

let client = null;
let memoryDb = null;

const MEMORY_URL = 'memory://';

function memPersist() {
  if (!config.memoryDbFile) return;
  const payload = { name: memoryDb.name, cols: {} };
  for (const [name, col] of memoryDb.cols.entries()) payload.cols[name] = col.docs;
  fs.writeFileSync(config.memoryDbFile, JSON.stringify(payload));
}

function memLoad() {
  if (!config.memoryDbFile || !fs.existsSync(config.memoryDbFile)) return;
  const payload = JSON.parse(fs.readFileSync(config.memoryDbFile, 'utf8'));
  memoryDb = new MemDb(payload.name);
  for (const [name, docs] of Object.entries(payload.cols || {})) {
    const col = memoryDb.collection(name);
    col.docs = docs;
  }
}

// ── In-memory Mongo-subset ──────────────────────────────────────────────────
const inList = (list, val) => {
  if (list == null) return false;
  if (Array.isArray(list)) return list.includes(val);
  if (typeof list.has === 'function') return list.has(val);
  return [...list].includes(val);
};

function matches(doc, filter) {
  if (!filter) return true;
  return Object.entries(filter).every(([key, cond]) => {
    const val = doc?.[key];
    if (cond === null) return val === null;
    if (typeof cond === 'object' && cond !== null && !Array.isArray(cond)) {
      if ('$in' in cond) return inList(cond.$in, val);
      if ('$nin' in cond) return !inList(cond.$nin, val);
      if ('$eq' in cond) return val === cond.$eq;
      return Object.entries(cond).every(([op, v]) => {
        if (op === '$in') return inList(v, val);
        if (op === '$nin') return !inList(v, val);
        if (op === '$ne') return val !== v;
        return false;
      });
    }
    return val === cond;
  });
}

function applySet(doc, set) {
  for (const [k, v] of Object.entries(set || {})) doc[k] = v;
  return doc;
}

class MemCollection {
  constructor(name) {
    this.name = name;
    this.docs = [];
  }
  async createIndex() {}
  async insertOne(doc) {
    this.docs.push(JSON.parse(JSON.stringify(doc)));
    memPersist();
  }
  async replaceOne(filter, doc, { upsert = false } = {}) {
    const idx = this.docs.findIndex((d) => matches(d, filter));
    if (idx === -1) {
      if (upsert) this.docs.push(JSON.parse(JSON.stringify(doc)));
    } else {
      this.docs[idx] = JSON.parse(JSON.stringify(doc));
    }
    memPersist();
  }
  async updateOne(filter, update, { upsert = false } = {}) {
    let doc = this.docs.find((d) => matches(d, filter));
    if (!doc) {
      if (upsert) {
        doc = {};
        for (const [k, cond] of Object.entries(filter || {})) {
          doc[k] = typeof cond === 'object' && cond && '$in' in cond ? [...cond.$in][0] : cond;
        }
        this.docs.push(doc);
      } else return;
    }
    if (update.$set) applySet(doc, update.$set);
    if (update.$setOnInsert && !doc._setOnInsertDone) {
      applySet(doc, update.$setOnInsert);
      doc._setOnInsertDone = true;
    }
    memPersist();
  }
  async updateMany(filter, update) {
    let changed = 0;
    for (const doc of this.docs.filter((d) => matches(d, filter))) {
      if (update.$set) applySet(doc, update.$set);
      changed++;
    }
    if (changed) memPersist();
  }
  async countDocuments(filter = {}) {
    return this.docs.filter((d) => matches(d, filter)).length;
  }
  async findOne(filter = {}) {
    const doc = this.docs.find((d) => matches(d, filter));
    return doc ? JSON.parse(JSON.stringify(doc)) : null;
  }
  find(filter = {}, options = {}) {
    let docs = this.docs.filter((d) => matches(d, filter)).map((d) => JSON.parse(JSON.stringify(d)));
    const { projection, sort } = options || {};
    if (sort) {
      const [key, dir] = Object.entries(sort)[0];
      docs.sort((a, b) => (dir === -1 ? (a[key] < b[key] ? 1 : a[key] > b[key] ? -1 : 0) : a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0));
    }
    if (projection) {
      docs = docs.map((d) => {
        const out = {};
        for (const [k, v] of Object.entries(projection)) if (v) out[k] = d[k];
        return out;
      });
    }
    return {
      sort: () => this.find(filter, { ...options, sort: options?.sort }),
      limit: (n) => ({ toArray: async () => docs.slice(0, n) }),
      toArray: async () => docs,
    };
  }
}

class MemDb {
  constructor(name) {
    this.name = name;
    this.cols = new Map();
  }
  collection(name) {
    if (!this.cols.has(name)) this.cols.set(name, new MemCollection(name));
    return this.cols.get(name);
  }
}

// ── Connection ──────────────────────────────────────────────────────────────
export async function getDb() {
  if (config.mongoUrl === MEMORY_URL) {
    if (!memoryDb) {
      memLoad();
      if (!memoryDb) {
        memoryDb = new MemDb(config.dbName);
        console.warn('[db] using in-memory store (MONGO_URL=memory://) — dev/test only');
      }
    }
    return memoryDb;
  }
  if (!client) {
    client = new MongoClient(config.mongoUrl, { serverSelectionTimeoutMS: 8000 });
    await client.connect();
  }
  return client.db(config.dbName);
}

export async function closeDb() {
  if (client) {
    await client.close();
    client = null;
  }
}

export const COLLECTIONS = {
  questions: 'content_questions',
  scenarios: 'content_scenarios',
  chapters: 'content_chapters',
  releases: 'content_releases',
  audit: 'content_audit',
};

export async function ensureIndexes(db) {
  const idx = {
    questions: [{ key: { chapterId: 1, status: 1 } }, { key: { status: 1 } }, { key: { subject: 1 } }, { key: { id: 1 } }],
    scenarios: [{ key: { chapterId: 1, status: 1 } }, { key: { scenarioId: 1 } }],
    chapters: [{ key: { chapterId: 1 } }, { key: { status: 1 } }],
    releases: [{ key: { revision: 1 } }],
    audit: [{ key: { entityId: 1 } }, { key: { at: -1 } }],
  };
  for (const [name, list] of Object.entries(idx)) {
    const col = db.collection(COLLECTIONS[name]);
    for (const spec of list) {
      try {
        await col.createIndex(spec.key);
      } catch (e) {
        // ignore index name conflicts
      }
    }
  }
}
