/**
 * The boundary contract.
 *
 * Every shape SPECTRA's API can put on the wire is declared here and parsed
 * before it reaches a component. `docs/api.md` plus
 * `packages/schemas/spectra_schemas/` are authoritative; these schemas mirror
 * them and nothing else in the app is allowed to assume a field exists.
 *
 * Fields the API documentation does not specify are marked at their definition
 * and parsed permissively, so an unspecified row degrades field by field
 * instead of failing the whole screen.
 */
export * from './schemas/primitives';
export * from './schemas/search';
export * from './schemas/system';
