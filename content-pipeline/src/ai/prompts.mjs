// Prompt assembly for chapter-wise AI generation.
// Discipline enforced here:
//  - ICAI modules: concepts, rules, provisions, definitions, official terminology, scope
//  - RTP: amendment emphasis, attempt-specific areas, application style
//  - MTP: mock difficulty, multi-step application, time-pressure style
//  - PYQ: historical difficulty, repeated concepts, framing, distractor quality
//  - Calibration ONLY: never copy ICAI/RTP/MTP/PYQ wording verbatim
//  - Exactly one correct answer; all distractors must be defensible wrong answers
//  - Attempt-specific legal/tax facts must be flagged `attemptSpecificRisk: true`
//  - No student data is ever present in these prompts.

import { config } from '../lib/config.mjs';

const SYSTEM = `You are a senior CA Intermediate examination author working for a coaching mentorship platform.
You write original multiple-choice questions calibrated to the ICAI examination style.
STRICT RULES:
1. Use official ICAI terminology, definitions, provisions and scope from the module excerpts provided.
2. RTP/MTP/PYQ excerpts are provided ONLY for calibration of difficulty, style, application depth and distractor quality.
   NEVER reproduce their wording or questions verbatim, and never copy module sentences verbatim into options or explanations.
3. Every question must have EXACTLY one correct answer. All distractors must be plausible, defensible wrong answers
   that reflect common student errors.
4. If a question depends on attempt-specific law, rates, dates or limits, set "attemptSpecificRisk": true and state the
   attempt assumed in the explanation.
5. Keep questions application-oriented and exam-relevant. Vary difficulty across the set (easy/moderate/hard).
6. Every question must include icaiSourceRefs (module reference with section/provision where applicable) and
   calibrationRefs (RTP/MTP/PYQ reference used as benchmark). Never fabricate references.
7. Respond with ONLY the JSON object requested. No markdown fences, no commentary.`;

const budget = (text, chars) => {
  const s = String(text || '');
  return s.length <= chars ? s : `${s.slice(0, chars)} …[truncated]`;
};

function chapterContext(chapter, mapping) {
  const parts = [
    `SUBJECT: ${chapter.subject}`,
    `PAPER: ${chapter.paper}`,
    `SECTION/PART: ${chapter.section}`,
    `MODULE: ${chapter.module}`,
    `CHAPTER ${chapter.chapterNumber}: ${chapter.chapterTitle}`,
    `GROUP: ${chapter.group}`,
  ];
  if (chapter.learningPoints?.length) {
    parts.push(`OFFICIAL LEARNING POINTS / CONCEPTS:\n- ${chapter.learningPoints.join('\n- ')}`);
  }
  if (mapping) {
    const moduleText = (mapping.moduleFragmentTexts || []).join('\n\n');
    if (moduleText.trim()) parts.push(`ICAI MODULE EXCERPTS (concepts/rules/provisions/definitions — do NOT copy verbatim):\n${budget(moduleText, 24000)}`);
    const rtp = (mapping.rtpFragmentTexts || []).join('\n\n');
    if (rtp.trim()) parts.push(`RTP EXCERPTS (calibration: recent amendments, attempt-specific emphasis, application style):\n${budget(rtp, 5000)}`);
    const mtp = (mapping.mtpFragmentTexts || []).join('\n\n');
    if (mtp.trim()) parts.push(`MTP EXCERPTS (calibration: mock difficulty, multi-step application, time-pressure style):\n${budget(mtp, 5000)}`);
    const pyq = (mapping.pyqFragmentTexts || []).join('\n\n');
    if (pyq.trim()) parts.push(`PYQ EXCERPTS (calibration: historical difficulty, repeated concepts, framing, distractor quality):\n${budget(pyq, 5000)}`);
  }
  return parts.join('\n\n');
}

const MCQ_JSON_CONTRACT = `{
  "prompt": "question stem (string)",
  "options": [ { "id": "A", "text": "…" }, { "id": "B", "text": "…" }, { "id": "C", "text": "…" }, { "id": "D", "text": "…" } ],
  "correctOptionId": "A",
  "explanation": "clear explanation with rule/provision basis (string)",
  "difficulty": "easy | moderate | hard",
  "conceptTags": ["2-4 short tags in lowercase kebab-case"],
  "icaiSourceRefs": [ { "source": "module", "module": "…", "chapter": 1, "section": "…", "provision": "…", "edition": "May 2026" } ],
  "calibrationRefs": [ { "source": "RTP|MTP|PYQ", "attempt": "…", "questionRef": "…", "calibrationNote": "what was benchmarked" } ],
  "attemptSpecificRisk": false
}`;

export function plainMcqPrompt(chapter, mapping, { index, total, difficulty }) {
  return `${chapterContext(chapter, mapping)}

TASK: Write ONE original, application-oriented plain MCQ for this chapter.
Difficulty target: ${difficulty}. This is question ${index + 1} of ${total} plain MCQs for the chapter.
Use RTP/MTP/PYQ ONLY for calibration — do not copy any source wording.

Respond with ONLY this JSON object:
${MCQ_JSON_CONTRACT}`;
}

export function scenarioPrompt(chapter, mapping, { index, total }) {
  const contractLines = MCQ_JSON_CONTRACT.split('\n').map((l) => `    ${l}`).join('\n');
  return `${chapterContext(chapter, mapping)}

TASK: Write ONE original case SCENARIO for this chapter — a shared passage followed by EXACTLY FOUR linked
MCQs (one correct answer each). This is scenario ${index + 1} of ${total} for the chapter.
The passage should present a realistic practical situation (facts, figures, parties) that students apply the
chapter's rules to. The four questions must build on the same facts, each testing a different concept/angle,
in increasing order of application depth (question sequence 1→4).
Difficulty: mix moderate and hard across the four questions.
Use RTP/MTP/PYQ ONLY for calibration — do not copy any source wording.

Respond with ONLY this JSON object:
{
  "passage": "shared case scenario passage (string)",
  "questions": [
${contractLines},
${contractLines},
${contractLines},
${contractLines}
  ],
  "icaiSourceRefs": [ { "source": "module", "module": "…", "chapter": 1, "section": "…", "provision": "…", "edition": "May 2026" } ],
  "calibrationRefs": [ { "source": "RTP|MTP|PYQ", "attempt": "…", "questionRef": "…", "calibrationNote": "…" } ],
  "attemptSpecificRisk": false
}`;
}

export function distractorSelfCheckPrompt(chapter, questionJson) {
  return `${chapterContext(chapter, null)}

The following question was generated for this chapter:
${JSON.stringify(questionJson, null, 2)}

TASK: Verify:
1. Exactly ONE option is correct — the other three must be unambiguously wrong under ICAI rules.
2. No option or explanation copies ICAI/RTP/MTP/PYQ wording verbatim.
3. difficulty and conceptTags are appropriate.
If ALL checks pass respond with {"verdict":"pass"}.
Otherwise respond with {"verdict":"fail","reason":"…","fix":"…"} and provide the corrected question as "corrected".
Respond with ONLY the JSON object.`;
}

export const SYSTEM_PROMPT = SYSTEM;
export { chapterContext };
