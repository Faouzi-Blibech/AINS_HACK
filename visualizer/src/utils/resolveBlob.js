import { MOCK_BLOBS } from "../mocks/mock_blobs.js";

// Resolve a "sha256:<hash>" ref to its recorded content, or null if unknown.
// (Mock-backed for now; later this becomes a fetch to the resolved-step API.)
export function resolveBlob(ref) {
  if (!ref) return null;
  return ref in MOCK_BLOBS ? MOCK_BLOBS[ref] : null;
}
