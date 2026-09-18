/** One place that owns every TanStack Query cache key. */
export const queryKeys = {
  health: ['health'] as const,
  models: ['models'] as const,
  agents: ['agents'] as const,
  sources: ['sources'] as const,
  sourceHealth: (id: string) => ['sources', id, 'health'] as const,
  investigations: ['investigations'] as const,
  investigation: (id: string) => ['investigations', id] as const,
  investigationTrace: (id: string) => ['investigations', id, 'trace'] as const,
  investigationAutopsy: (id: string) => ['investigations', id, 'autopsy'] as const,
  investigationGraph: (id: string) => ['investigations', id, 'graph'] as const,
  cases: ['cases'] as const,
  graph: (nodeId: string, depth: number, types: string) => ['graph', nodeId, depth, types] as const,
  entity: (id: string) => ['entities', id] as const,
  entitySearch: (query: string) => ['entities', 'search', query] as const,
  evidence: (id: string) => ['evidence', id] as const,
  asset: (id: string) => ['assets', id] as const,
  uploadJob: (id: string) => ['uploads', id] as const,
  demoScenarios: ['demo', 'scenarios'] as const,
} as const;

export const POLL_INTERVAL_MS = {
  health: 20_000,
  models: 5_000,
  uploadJob: 1_500,
} as const;
