export function checkPackage(bytes: Uint8Array, fingerprint: string): string[];
export function reportOf(bytes: Uint8Array): { title: string; prepared_for: string } | null;
export function flipManifestByte(bytes: Uint8Array): Uint8Array;
export function devPassword(): string;
