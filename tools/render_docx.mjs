// Optional, local LibreOffice Writer/WASM validation (not a production exporter).
// Install the pinned converter into an ignored prefix; see the integration audit.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const manifest = process.argv[2];
if (!manifest) {
  console.error('Usage: CV_LO_PREFIX=generated/word-render-env node tools/render_docx.mjs generated/cv-validation/cases.json');
  process.exit(2);
}
const prefix = path.resolve(process.env.CV_LO_PREFIX || 'generated/word-render-env');
const require = createRequire(path.join(prefix, 'package.json'));
const { createSubprocessConverter } = require('@matbee/libreoffice-converter');
const packageDir = path.dirname(require.resolve('@matbee/libreoffice-converter/package.json'));
const cases = JSON.parse(fs.readFileSync(manifest, 'utf8'));
const converter = await createSubprocessConverter({
  includeSystemFonts: true,
  wasmPath: path.join(packageDir, 'wasm'),
});
let status = 0;
try {
  for (const { paths } of Object.values(cases)) {
    const result = await converter.convert(fs.readFileSync(paths.docx), { outputFormat: 'pdf' }, path.basename(paths.docx));
    const folder = path.join(path.dirname(paths.docx), 'libreoffice');
    fs.mkdirSync(folder, { recursive: true });
    const output = path.join(folder, path.basename(paths.docx, '.docx') + '.pdf');
    fs.writeFileSync(output, result.data);
    console.log(output);
  }
} catch (error) {
  console.error(error);
  status = 1;
} finally {
  await converter.destroy();
}
// Version 2.7.2 leaves request-timeout timers after destroying the subprocess.
// Every conversion above is awaited and written synchronously before exit.
process.exit(status);
