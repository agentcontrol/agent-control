/* eslint-disable @typescript-eslint/no-var-requires */
// Post-process Playwright raw V8 coverage into an Istanbul HTML report.
//
// Input:
//   - JSON files under playwright-coverage/raw/<project>/*.json
//     (emitted by the shared Playwright fixture in tests/fixtures.ts)
//
// Output:
//   - Istanbul HTML + text-summary under coverage-playwright/
//   - LCOV file (lcov.info) under coverage-playwright/ for Codecov

const fs = require('node:fs/promises');
const path = require('node:path');

const v8ToIstanbul = require('v8-to-istanbul');
const istanbulLibCoverage = require('istanbul-lib-coverage');
const istanbulLibReport = require('istanbul-lib-report');
const istanbulReports = require('istanbul-reports');

async function listJsonFiles(dir) {
  const files = [];
  async function walk(current) {
    let entries;
    try {
      entries = await fs.readdir(current, { withFileTypes: true });
    } catch (err) {
      if (err && err.code === 'ENOENT') return;
      throw err;
    }

    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.json')) {
        files.push(fullPath);
      }
    }
  }

  await walk(dir);
  return files;
}

async function main() {
  const cwd = process.cwd();
  const rawRoot = path.join(cwd, 'playwright-coverage', 'raw');

  const files = await listJsonFiles(rawRoot);
  if (files.length === 0) {
    // eslint-disable-next-line no-console
    console.warn(
      '[coverage-playwright] No raw coverage files found under',
      rawRoot
    );
    return;
  }

  const coverageMap = istanbulLibCoverage.createCoverageMap({});

  for (const file of files) {
    // eslint-disable-next-line no-console
    console.log('[coverage-playwright] Processing', path.relative(cwd, file));
    const jsonText = await fs.readFile(file, 'utf-8');
    /** @type {Array<{ url?: string; source?: string; functions: any[] }>} */
    const entries = JSON.parse(jsonText);

    for (const entry of entries) {
      if (!entry || !entry.source || !entry.functions) continue;

      // Use the URL path (if present) as a pseudo file path in reports.
      let virtualPath = entry.url || 'anonymous-script.js';
      try {
        if (virtualPath.startsWith('http://') || virtualPath.startsWith('https://')) {
          const u = new URL(virtualPath);
          virtualPath = u.pathname || virtualPath;
        }
      } catch {
        // Keep original value if URL parsing fails
      }

      const converter = v8ToIstanbul(virtualPath, 0, {
        source: entry.source,
      });
      await converter.load();
      await converter.applyCoverage(entry.functions);

      const fileCoverage = converter.toIstanbul();

      // Only keep coverage for UI application sources under src/.
      // This filters out Next.js internals and node_modules noise.
      const filtered = istanbulLibCoverage.createCoverageMap({});
      for (const filePath of Object.keys(fileCoverage)) {
        if (
          filePath.includes('/src/') ||
          filePath.includes('\\src\\') ||
          filePath.startsWith('src/')
        ) {
          filtered.addFileCoverage(fileCoverage[filePath]);
        }
      }

      coverageMap.merge(filtered);
    }
  }

  const outDir = path.join(cwd, 'coverage-playwright');
  await fs.mkdir(outDir, { recursive: true });

  const context = istanbulLibReport.createContext({
    dir: outDir,
    coverageMap,
  });

  const reports = [
    istanbulReports.create('html'),
    istanbulReports.create('text-summary'),
    // LCOV format that Codecov, Coveralls, etc. understand.
    istanbulReports.create('lcovonly', { file: 'lcov.info' }),
  ];

  for (const report of reports) {
    report.execute(context);
  }

  // eslint-disable-next-line no-console
  console.log(
    '[coverage-playwright] HTML report written to',
    path.join('coverage-playwright', 'index.html')
  );
  console.log(
    '[coverage-playwright] LCOV report written to',
    path.join('coverage-playwright', 'lcov.info')
  );
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error('[coverage-playwright] Failed:', err);
  process.exitCode = 1;
});

