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
import type { AgentName } from '@/lib/schemas/primitives';

const AGENT_ICON: Record<AgentName, ComponentType<IconProps>> = {
  brain: IconBrain,
  document_agent: IconDocument,
  vision_agent: IconImage,
  video_agent: IconVideo,
  audio_agent: IconAudio,
  database_agent: IconDatabase,
  graph_agent: IconGraph,
  entity_resolver: IconEntity,
  hypothesis_engine: IconBrain,
  disproof_agent: IconDisproof,
  verifier: IconVerifier,
  timeline_builder: IconTimeline,
  contradiction_radar: IconWarning,
};

/** Each agent gets one drawn glyph, consistent everywhere it appears. */
export function AgentGlyph({ agent, size = 14 }: { agent: AgentName; size?: number }) {
  const Glyph = AGENT_ICON[agent];
  return <Glyph size={size} />;
}
