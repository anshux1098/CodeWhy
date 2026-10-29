/**
 * Resolve a branch name from a repository's free-form scope string.
 * The backend has no branch column, so the scope text is the only source.
 * Returns null when the text is missing, malformed, or a placeholder.
 */
export function branchFromScope(scope: string | null | undefined): string | null {
  if (!scope) return null;
  const match = scope.match(/at branch\s+([^,;]+)/i);
  if (!match) return null;
  const branch = match[1].trim();
  if (!branch) return null;
  if (branch.toLowerCase() === 'the ingested branch') return null;
  if (branch.length > 64) return null;
  if (/\s/.test(branch)) return null;
  return branch;
}
