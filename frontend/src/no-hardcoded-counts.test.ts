import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { join } from 'path';

function walkDir(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...walkDir(full));
    } else if (/\.(ts|tsx)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

describe('no hard-coded repository counts', () => {
  it('src does not contain the old made-up counts (48, 142, 120)', () => {
    const srcDir = join(process.cwd(), 'src');
    const files = walkDir(srcDir);
    const offenders: string[] = [];
    for (const file of files) {
      if (file.includes('no-hardcoded-counts.test.ts')) continue;
      const content = readFileSync(file, 'utf-8');
      // Check for the specific old made-up counts in context of repository data
      if (content.includes('decisions: 48') || content.includes('entities: 142') || content.includes('pull_requests: 120')) {
        offenders.push(file.replace(process.cwd() + '/', ''));
      }
    }
    expect(offenders).toEqual([]);
  });
});