// Playwright's API returns Node Buffers. The e2e project has no @types/node, so describe
// Buffer as the Uint8Array it extends; that is all these tests use.
declare class Buffer extends Uint8Array {}
