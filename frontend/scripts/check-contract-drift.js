import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const schemaPath = path.join(rootDir, 'src', 'api', 'schema.ts');
const tmpSchemaPath = path.join(rootDir, 'src', 'api', 'schema.tmp.ts');
const openapiPath = path.join(rootDir, 'fixtures', 'recorded', 'openapi.json');

try {
  console.log('Running contract drift check against fixtures/recorded/openapi.json...');
  execSync(`pnpm exec openapi-typescript "${openapiPath}" -o "${tmpSchemaPath}"`, {
    cwd: rootDir,
    stdio: 'inherit',
  });

  const existing = fs.readFileSync(schemaPath, 'utf8').replace(/\r\n/g, '\n');
  const generated = fs.readFileSync(tmpSchemaPath, 'utf8').replace(/\r\n/g, '\n');

  if (existing !== generated) {
    console.error('❌ Contract drift detected! src/api/schema.ts differs from fixtures/recorded/openapi.json.');
    console.error('Run "pnpm run typegen" to synchronize schema.ts with openapi.json.');
    fs.unlinkSync(tmpSchemaPath);
    process.exit(1);
  }

  fs.unlinkSync(tmpSchemaPath);
  console.log('✅ Contract check passed: src/api/schema.ts is up to date.');
} catch (err) {
  if (fs.existsSync(tmpSchemaPath)) {
    fs.unlinkSync(tmpSchemaPath);
  }
  console.error('Error during contract check:', err.message);
  process.exit(1);
}
