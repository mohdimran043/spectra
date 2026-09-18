import type { ComponentType } from 'react';

import {
  IconAudio,
  IconBrain,
  IconDatabase,
  IconDisproof,
  IconDocument,
  IconEntity,
  IconGraph,
  IconImage,
  IconTimeline,
  IconVerifier,
  IconVideo,
  IconWarning,
  type IconProps,
} from '@/components/icons';
import { agentNameSchema, type AgentName } from '@/lib/schemas/primitives';

const AGENT_ICON: Record<AgentName, ComponentType<IconProps>> = {
  brain: IconBrain,
  document_agent: IconDocument,
  vision_agent: IconImage,
  video_agent: IconVideo,
  audio_agent: IconAudio,
  database_agent: IconDatabase,
  graph_agent: IconGraph,
  entity_resolver: IconEntity,
  claim_builder: IconBrain,
  disproof_agent: IconDisproof,
  verifier: IconVerifier,
  timeline_builder: IconTimeline,
  contradiction_radar: IconWarning,
};

const AGENT_NAMES: ReadonlySet<string> = new Set<string>(agentNameSchema.options);

/**
 * `GET /api/agents/status` reports the toggleable flag (`claim`, `vision`) as
 * well as the agent it belongs to (`claim_builder`, `vision_agent`), so a row
 * can arrive under either name. Anything outside the contract's vocabulary
 * resolves to `null` and renders without a glyph rather than guessing.
 */
const FLAG_ALIAS: Readonly<Record<string, AgentName>> = {
  claim: 'claim_builder',
  disproof: 'disproof_agent',
  document: 'document_agent',
  vision: 'vision_agent',
  image: 'vision_agent',
  video: 'video_agent',
  audio: 'audio_agent',
  database: 'database_agent',
  graph: 'graph_agent',
  timeline: 'timeline_builder',
  contradiction: 'contradiction_radar',
};

export function resolveAgentName(name: string): AgentName | null {
  if (AGENT_NAMES.has(name)) return name as AgentName;
  return FLAG_ALIAS[name] ?? null;
}

/** Each agent gets one drawn glyph, consistent everywhere it appears. */
export function AgentGlyph({ agent, size = 14 }: { agent: AgentName; size?: number }) {
  const Glyph = AGENT_ICON[agent];
  return <Glyph size={size} />;
}
