// Pluggable AI provider adapters (fetch-based; no vendor SDKs).
// Every adapter implements: complete({ system, user, jsonSchemaHint })
// → returns parsed JSON (when json mode requested) or plain text.
// Provider calls NEVER include student data — only catalog + ICAI sources.

import { config, fail } from '../lib/config.mjs';

function assertJson(text, fallback) {
  const cleaned = String(text)
    .replace(/^```(?:json)?\s*/m, '')
    .replace(/```\s*$/, '')
    .trim();
  try {
    return JSON.parse(cleaned);
  } catch (e) {
    if (fallback !== undefined) return fallback;
    throw new Error(`AI response is not valid JSON: ${String(e).slice(0, 200)}`);
  }
}

async function postJson(url, headers, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`AI provider HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

// ── OpenAI-compatible (default primary) ────────────────────────────────────
const openaiAdapter = {
  name: 'openai',
  async complete({ system, user, json = false, temperature = 0.4, maxTokens = 4096 }) {
    if (!config.openai.apiKey) fail('generate', 'OPENAI_API_KEY is not set');
    const data = await postJson(`${config.openai.baseUrl.replace(/\/$/, '')}/chat/completions`, {
      Authorization: `Bearer ${config.openai.apiKey}`,
    }, {
      model: config.openai.model,
      temperature,
      max_tokens: maxTokens,
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: user },
      ],
      ...(json ? { response_format: { type: 'json_object' } } : {}),
    });
    const content = data?.choices?.[0]?.message?.content;
    if (content == null) throw new Error('empty AI response');
    return json ? assertJson(content) : content;
  },
};

// ── Anthropic ──────────────────────────────────────────────────────────────
const anthropicAdapter = {
  name: 'anthropic',
  async complete({ system, user, json = false, temperature = 0.4, maxTokens = 4096 }) {
    if (!config.anthropic.apiKey) fail('generate', 'ANTHROPIC_API_KEY is not set');
    const data = await postJson('https://api.anthropic.com/v1/messages', {
      'x-api-key': config.anthropic.apiKey,
      'anthropic-version': '2023-06-01',
    }, {
      model: config.anthropic.model,
      max_tokens: maxTokens,
      temperature,
      system,
      messages: [{ role: 'user', content: `${user}${json ? '\n\nRespond with ONLY a valid JSON object, no commentary.' : ''}` }],
    });
    const content = Array.isArray(data?.content) ? data.content.map((b) => b.text || '').join('') : '';
    if (!content) throw new Error('empty AI response');
    return json ? assertJson(content) : content;
  },
};

// ── Google Gemini ──────────────────────────────────────────────────────────
const geminiAdapter = {
  name: 'gemini',
  async complete({ system, user, json = false, temperature = 0.4, maxTokens = 4096 }) {
    if (!config.gemini.apiKey) fail('generate', 'GEMINI_API_KEY is not set');
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${config.gemini.model}:generateContent?key=${config.gemini.apiKey}`;
    const data = await postJson(url, {}, {
      system_instruction: { parts: [{ text: system }] },
      contents: [{ role: 'user', parts: [{ text: user }] }],
      generationConfig: {
        temperature,
        maxOutputTokens: maxTokens,
        ...(json ? { responseMimeType: 'application/json' } : {}),
      },
    });
    const text = data?.candidates?.[0]?.content?.parts?.map((p) => p.text || '').join('') || '';
    if (!text) throw new Error('empty AI response');
    return json ? assertJson(text) : text;
  },
};

const ADAPTERS = { openai: openaiAdapter, anthropic: anthropicAdapter, gemini: geminiAdapter };

export function getAdapter(name = config.aiProvider) {
  const adapter = ADAPTERS[name];
  if (!adapter) fail('generate', `unknown AI_PROVIDER "${name}" (openai | anthropic | gemini)`);
  return adapter;
}

export { assertJson };
