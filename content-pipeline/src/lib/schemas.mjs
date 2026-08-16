// JSON Schemas for the content model (§4 of docs/integration-design.md).
// These are the SOURCE OF TRUTH for schema validation (stage 6) and are
// mirrored by the FastAPI backend's pydantic models.

export const DIFFICULTIES = ['easy', 'moderate', 'hard'];
export const STATUSES = [
  'generated', 'auto_validated', 'needs_review', 'changes_requested',
  'rejected', 'approved', 'release_candidate', 'published', 'superseded',
];
export const SOURCE_TYPES = ['module', 'rtp', 'mtp', 'pyq'];

export const optionSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'text'],
  properties: {
    id: { type: 'string', minLength: 1, maxLength: 4 },
    text: { type: 'string', minLength: 1 },
  },
};

export const sourceRefSchema = {
  type: 'object',
  additionalProperties: true,
  required: ['source'],
  properties: {
    source: { enum: ['module', 'RTP', 'MTP', 'PYQ'] },
  },
};

export const scenarioLinkSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['scenarioId', 'seq', 'blockTotal'],
  properties: {
    scenarioId: { type: 'string', minLength: 1 },
    seq: { type: 'integer', minimum: 1 },
    blockTotal: { type: 'integer', minimum: 2 },
  },
};

export const questionSchema = {
  type: 'object',
  additionalProperties: true,
  required: [
    'id', 'revision', 'chapterId', 'subject', 'paper', 'section', 'module',
    'chapterNumber', 'chapterTitle', 'questionType', 'difficulty', 'conceptTags',
    'prompt', 'options', 'correctOptionId', 'explanation', 'icaiSourceRefs',
    'calibrationRefs', 'generationMeta', 'scenario', 'status', 'statusHistory',
  ],
  properties: {
    id: { type: 'string', minLength: 1, pattern: '^adp_' },
    revision: { type: 'integer', minimum: 1 },
    chapterId: { type: 'string', minLength: 1 },
    subject: { type: 'string' },
    paper: { type: 'string' },
    section: { type: 'string' },
    module: { type: 'string' },
    chapterNumber: { type: ['integer', 'number'] },
    chapterTitle: { type: 'string' },
    questionType: { enum: ['mcq', 'scenario_mcq'] },
    difficulty: { enum: DIFFICULTIES },
    conceptTags: { type: 'array', items: { type: 'string' }, minItems: 1 },
    prompt: { type: 'string', minLength: 10 },
    options: { type: 'array', items: optionSchema, minItems: 4, maxItems: 4 },
    correctOptionId: { type: 'string', minLength: 1 },
    explanation: { type: 'string', minLength: 10 },
    icaiSourceRefs: { type: 'array', items: sourceRefSchema, minItems: 1 },
    calibrationRefs: { type: 'array', items: sourceRefSchema, minItems: 1 },
    generationMeta: { type: 'object', required: ['model', 'promptVersion', 'generatedAt'] },
    scenario: { oneOf: [{ type: 'null' }, scenarioLinkSchema] },
    attemptSpecificRisk: { type: 'boolean' },
    validation: {
      type: 'object',
      properties: {
        errors: { type: 'array', items: { type: 'string' } },
        warnings: { type: 'array', items: { type: 'string' } },
      },
    },
    similarity: { type: 'object' },
    status: { enum: STATUSES },
    statusHistory: { type: 'array', items: { type: 'object' }, minItems: 1 },
    approval: { oneOf: [{ type: 'null' }, { type: 'object' }] },
  },
};

export const scenarioSchema = {
  type: 'object',
  additionalProperties: true,
  required: [
    'scenarioId', 'revision', 'chapterId', 'passage', 'icaiSourceRefs',
    'calibrationRefs', 'questionIds', 'status', 'statusHistory',
  ],
  properties: {
    scenarioId: { type: 'string', minLength: 1, pattern: '^adp_s_' },
    revision: { type: 'integer', minimum: 1 },
    chapterId: { type: 'string', minLength: 1 },
    passage: { type: 'string', minLength: 40 },
    icaiSourceRefs: { type: 'array', items: sourceRefSchema, minItems: 1 },
    calibrationRefs: { type: 'array', items: sourceRefSchema, minItems: 1 },
    questionIds: { type: 'array', items: { type: 'string' }, minItems: 4, maxItems: 4 },
    attemptSpecificRisk: { type: 'boolean' },
    status: { enum: STATUSES },
    statusHistory: { type: 'array', items: { type: 'object' }, minItems: 1 },
  },
};

export const manifestSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['schemaVersion', 'revision', 'publishedAt', 'publishedBy', 'catalogRevision', 'chapters'],
  properties: {
    schemaVersion: { type: 'integer', minimum: 1 },
    revision: { type: 'integer', minimum: 1 },
    publishedAt: { type: 'string' },
    publishedBy: { type: 'string' },
    catalogRevision: { type: 'string' },
    chapters: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        required: ['chapterId', 'counts', 'questionIds', 'chunkWeb', 'chunkMobile', 'contentHash'],
        properties: {
          chapterId: { type: 'string', minLength: 1 },
          counts: {
            type: 'object',
            required: ['plain', 'scenarios', 'scenarioMcqs', 'total'],
            properties: {
              plain: { type: 'integer' },
              scenarios: { type: 'integer' },
              scenarioMcqs: { type: 'integer' },
              total: { type: 'integer' },
            },
          },
          questionIds: { type: 'array', items: { type: 'string' } },
          chunkWeb: { type: 'string', minLength: 1 },
          chunkMobile: { type: 'string', minLength: 1 },
          contentHash: { type: 'string', pattern: '^sha256:' },
        },
      },
    },
    dailyMcqFrozen: { type: 'object' },
  },
};
