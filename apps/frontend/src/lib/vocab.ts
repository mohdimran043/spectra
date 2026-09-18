import type {
  AgentName,
  AnswerStatus,
  ClaimStatus,
  ConfidenceLabel,
  EvidenceStance,
  JobStatus,
  Modality,
  ModelState,
  SourceStatus,
  SourceType,
  TraceStatus,
} from './schemas/primitives';

/**
 * The record's vocabulary. Every closed enum the API can return has exactly one
 * operator-facing label and one status hue, declared here so a chip in the
 * evidence ledger and a chip in the autopsy can never disagree.
 */

export type StatusTone = 'seal' | 'stamp' | 'caution' | 'held' | 'quiet';

export const MODALITY_LABEL: Record<Modality, string> = {
  document: 'Document',
  image: 'Image',
  video: 'Video',
  audio: 'Audio',
  database: 'Database',
  graph: 'Graph',
  external: 'External',
};

/** The territory hue for each modality, as a CSS custom property name. */
export const MODALITY_VAR: Record<Modality, string> = {
  document: '--mod-document',
  image: '--mod-image',
  video: '--mod-video',
  audio: '--mod-audio',
  database: '--mod-database',
  graph: '--mod-graph',
  external: '--mod-external',
};

export const CLAIM_STATUS_LABEL: Record<ClaimStatus, string> = {
  supported: 'SUPPORTED',
  weak: 'WEAK',
  contradicted: 'CONTRADICTED',
  refuted: 'REFUTED',
  insufficient: 'INSUFFICIENT',
};

export const CLAIM_STATUS_TONE: Record<ClaimStatus, StatusTone> = {
  supported: 'seal',
  weak: 'caution',
  contradicted: 'stamp',
  refuted: 'stamp',
  insufficient: 'quiet',
};

/**
 * Each meaning is written about one statement alone. No status here describes a
 * ranking, because a claim is never judged against a rival claim — only against
 * the evidence found for and against it.
 */
export const CLAIM_STATUS_MEANING: Record<ClaimStatus, string> = {
  supported:
    'Carried by its own evidence, and the disproof probe found nothing that overturns it.',
  weak: 'Some support, but not enough independent corroboration to rely on.',
  contradicted: 'The disproof probe turned up an exhibit that conflicts with this statement.',
  refuted: 'The disproof probe found what it was looking for. This statement is ruled out.',
  insufficient: 'Not enough evidence was found either way to judge this statement.',
};

export const STANCE_LABEL: Record<EvidenceStance, string> = {
  supporting: 'Supporting',
  contradicting: 'Contradicting',
  neutral: 'Neutral',
};

export const STANCE_TONE: Record<EvidenceStance, StatusTone> = {
  supporting: 'seal',
  contradicting: 'stamp',
  neutral: 'quiet',
};

export const ANSWER_STATUS_LABEL: Record<AnswerStatus, string> = {
  supported: 'Supported',
  partially_supported: 'Partially supported',
  insufficient_evidence: 'Insufficient evidence',
  degraded: 'Degraded',
  failed: 'Failed',
};

export const ANSWER_STATUS_TONE: Record<AnswerStatus, StatusTone> = {
  supported: 'seal',
  partially_supported: 'caution',
  insufficient_evidence: 'stamp',
  degraded: 'caution',
  failed: 'stamp',
};

export const CONFIDENCE_LABEL_TEXT: Record<ConfidenceLabel, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  insufficient: 'Insufficient',
};

export const CONFIDENCE_TONE: Record<ConfidenceLabel, StatusTone> = {
  high: 'seal',
  medium: 'caution',
  low: 'caution',
  insufficient: 'stamp',
};

export const TRACE_STATUS_LABEL: Record<TraceStatus, string> = {
  started: 'Running',
  ok: 'Complete',
  empty: 'No results',
  skipped: 'Skipped',
  degraded: 'Degraded',
  error: 'Failed',
};

export const TRACE_STATUS_TONE: Record<TraceStatus, StatusTone> = {
  started: 'held',
  ok: 'seal',
  empty: 'quiet',
  skipped: 'quiet',
  degraded: 'caution',
  error: 'stamp',
};

export const SOURCE_STATUS_LABEL: Record<SourceStatus, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  unreachable: 'Unreachable',
  unconfigured: 'Unconfigured',
};

export const SOURCE_STATUS_TONE: Record<SourceStatus, StatusTone> = {
  healthy: 'seal',
  degraded: 'caution',
  unreachable: 'stamp',
  unconfigured: 'quiet',
};

export const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  local_folder: 'Local folder',
  s3: 'S3 bucket',
  postgres: 'PostgreSQL',
  mysql: 'MySQL',
  sqlite: 'SQLite',
  rest_api: 'REST API',
  upload: 'Uploads',
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Queued',
  processing: 'Processing',
  extracting: 'Extracting',
  embedding: 'Embedding',
  indexed: 'Indexed',
  ready: 'Ready',
  failed: 'Failed',
};

export const JOB_STAGES: readonly JobStatus[] = [
  'queued',
  'processing',
  'extracting',
  'embedding',
  'indexed',
  'ready',
];

export const MODEL_STATE_LABEL: Record<ModelState, string> = {
  unavailable: 'Unavailable',
  registered: 'Registered',
  loading: 'Loading',
  loaded: 'Loaded',
  unloading: 'Unloading',
  error: 'Error',
};

export const MODEL_STATE_TONE: Record<ModelState, StatusTone> = {
  unavailable: 'quiet',
  registered: 'held',
  loading: 'caution',
  loaded: 'seal',
  unloading: 'caution',
  error: 'stamp',
};

export const AGENT_LABEL: Record<AgentName, string> = {
  brain: 'Brain',
  document_agent: 'Document Agent',
  vision_agent: 'Vision Agent',
  video_agent: 'Video Agent',
  audio_agent: 'Audio Agent',
  database_agent: 'Database Agent',
  graph_agent: 'Knowledge Graph Agent',
  entity_resolver: 'Entity Resolver',
  claim_builder: 'Claim Builder',
  disproof_agent: 'Disproof Agent',
  verifier: 'Verifier',
  timeline_builder: 'Timeline Builder',
};

export const MODEL_ROLE_PURPOSE: Record<string, string> = {
  fast_brain: 'Routing and fast answers',
  deep_brain: 'Multi-step investigation reasoning',
  vision: 'Image and frame understanding',
  embedding: 'Text vector index',
  mm_embedding: 'Cross-modal vector index',
  reranker: 'Candidate reordering',
  speech: 'Audio transcription',
  ocr: 'Text recovery from pixels',
};

/** A best-effort human label for an id-shaped string. */
export function humaniseId(value: string): string {
  return value.replace(/^(src|ast|chk|evd|ent|inv|case|job|men|call|step)_/, '').replace(/_/g, ' ');
}

export function humaniseKey(value: string): string {
  return value
    .split('_')
    .map((word, index) => (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
    .join(' ');
}
