import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(frontendDir, '..');

const venvPythonWin = path.join(repoRoot, '.venv', 'Scripts', 'python.exe');
const venvPythonPosix = path.join(repoRoot, '.venv', 'bin', 'python');

let pythonCmd = 'python';
if (fs.existsSync(venvPythonWin)) {
  pythonCmd = venvPythonWin;
} else if (fs.existsSync(venvPythonPosix)) {
  pythonCmd = venvPythonPosix;
}

const recordScript = path.join(frontendDir, 'record_fixtures.py');
console.log(`Running fixture recording using: ${pythonCmd}`);
const result = spawnSync(pythonCmd, [recordScript], {
  cwd: frontendDir,
  stdio: 'inherit',
});

if (result.status !== 0) {
  process.exit(result.status || 1);
}
