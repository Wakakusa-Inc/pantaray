const fs = require('fs');
const nodeCrypto = require('crypto');
const path = require('path');

const HELPER_RUNTIME_RESOURCE_PATH = path.join('Contents', 'Resources', 'local_backend_helper');
const HELPER_RUNTIME_MANIFEST_FILENAME = 'runtime-manifest.json';
const DEFAULT_HELPER_PYTHON_RELATIVE_PATH = path.join('bin', 'python3');
const THIN_MACHO_MAGIC_HEX_VALUES = new Set(['feedface', 'cefaedfe', 'feedfacf', 'cffaedfe']);
const FAT_MACHO_MAGIC_BYTE_ORDER = new Map([
  ['cafebabe', 'BE'],
  ['bebafeca', 'LE'],
  ['cafebabf', 'BE'],
  ['bfbafeca', 'LE'],
]);
const MACHO_MAGIC_HEX_VALUES = new Set([
  ...THIN_MACHO_MAGIC_HEX_VALUES,
  'cafebabe',
  'bebafeca',
  'cafebabf',
  'bfbafeca',
]);
const MACHO_MAGIC_BYTE_LENGTH = 4;
const FAT_MACHO_HEADER_BYTE_LENGTH = 8;
const MAX_REASONABLE_FAT_ARCHITECTURES = 20;

function getLocalBackendHelperRoot(appPath) {
  return path.join(appPath, HELPER_RUNTIME_RESOURCE_PATH);
}

function sha256File(filePath) {
  const digest = nodeCrypto.createHash('sha256');
  digest.update(fs.readFileSync(filePath));
  return digest.digest('hex');
}

function isPathInsideOrEqual(candidatePath, rootPath) {
  const relativePath = path.relative(rootPath, candidatePath);
  return relativePath === '' || (!relativePath.startsWith('..') && !path.isAbsolute(relativePath));
}

function isMachOFile(filePath) {
  const buffer = Buffer.alloc(FAT_MACHO_HEADER_BYTE_LENGTH);
  const fd = fs.openSync(filePath, 'r');
  try {
    const bytesRead = fs.readSync(fd, buffer, 0, FAT_MACHO_HEADER_BYTE_LENGTH, 0);
    if (bytesRead < MACHO_MAGIC_BYTE_LENGTH) {
      return false;
    }
    const magic = buffer.subarray(0, MACHO_MAGIC_BYTE_LENGTH).toString('hex');
    if (THIN_MACHO_MAGIC_HEX_VALUES.has(magic)) {
      return true;
    }
    const byteOrder = FAT_MACHO_MAGIC_BYTE_ORDER.get(magic);
    if (!byteOrder || bytesRead < FAT_MACHO_HEADER_BYTE_LENGTH) {
      return false;
    }
    return isReasonableFatMachOArchitectureCount(buffer, byteOrder);
  } finally {
    fs.closeSync(fd);
  }
}

function isReasonableFatMachOArchitectureCount(headerBuffer, byteOrder) {
  const architectureCount =
    byteOrder === 'BE'
      ? headerBuffer.readUInt32BE(MACHO_MAGIC_BYTE_LENGTH)
      : headerBuffer.readUInt32LE(MACHO_MAGIC_BYTE_LENGTH);
  return architectureCount > 0 && architectureCount <= MAX_REASONABLE_FAT_ARCHITECTURES;
}

function assertNoSymlink(filePath) {
  const stat = fs.lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    throw new Error(`macOS signing does not allow helper runtime symlinks: ${filePath}`);
  }
  return stat;
}

function readJsonObject(filePath) {
  const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`Helper runtime manifest must be an object: ${filePath}`);
  }
  return parsed;
}

function writeJsonAtomically(targetPath, payload) {
  const tmpPath = `${targetPath}.tmp`;
  fs.writeFileSync(tmpPath, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: 'utf8',
    mode: 0o600,
  });
  fs.renameSync(tmpPath, targetPath);
}

function resolveHelperPythonExecutablePath(helperRoot, manifest) {
  const relativePath = String(
    manifest.python_executable_relative_path || DEFAULT_HELPER_PYTHON_RELATIVE_PATH
  ).trim();
  if (!relativePath || path.isAbsolute(relativePath)) {
    throw new Error(`Invalid helper python executable path: ${relativePath}`);
  }

  const executablePath = path.resolve(helperRoot, relativePath);
  if (!isPathInsideOrEqual(executablePath, path.resolve(helperRoot))) {
    throw new Error(`Helper python executable path escapes helper root: ${relativePath}`);
  }
  const stat = assertNoSymlink(executablePath);
  if (!stat.isFile()) {
    throw new Error(`Helper python executable is not a file: ${executablePath}`);
  }
  return executablePath;
}

function refreshSignedLocalBackendHelperManifest(appPath) {
  const helperRoot = getLocalBackendHelperRoot(appPath);
  if (!fs.existsSync(helperRoot)) {
    return { updated: false, reason: 'missing_helper_root', helperRoot };
  }

  const manifestPath = path.join(helperRoot, HELPER_RUNTIME_MANIFEST_FILENAME);
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Missing helper runtime manifest: ${manifestPath}`);
  }

  const manifest = readJsonObject(manifestPath);
  const pythonExecutablePath = resolveHelperPythonExecutablePath(helperRoot, manifest);
  const pythonSha256 = sha256File(pythonExecutablePath);
  writeJsonAtomically(manifestPath, {
    ...manifest,
    python_executable_sha256: pythonSha256,
  });
  return {
    updated: true,
    helperRoot,
    manifestPath,
    pythonExecutablePath,
    pythonSha256,
  };
}

function buildLocalBackendHelperSigningPlan(appPath) {
  const helperRoot = getLocalBackendHelperRoot(appPath);
  const signableFiles = [];
  const ignoredFiles = [];
  const pending = [helperRoot];

  if (!fs.existsSync(helperRoot)) {
    return { helperRoot, signableFiles, ignoredFiles };
  }

  while (pending.length > 0) {
    const currentPath = pending.pop();
    const stat = assertNoSymlink(currentPath);
    if (stat.isDirectory()) {
      for (const entryName of fs.readdirSync(currentPath)) {
        pending.push(path.join(currentPath, entryName));
      }
      continue;
    }
    if (!stat.isFile()) {
      throw new Error(`Unsupported helper runtime signing target: ${currentPath}`);
    }
    if (isMachOFile(currentPath)) {
      signableFiles.push(path.resolve(currentPath));
    } else {
      ignoredFiles.push(path.resolve(currentPath));
    }
  }

  return {
    helperRoot,
    signableFiles: signableFiles.sort(),
    ignoredFiles: ignoredFiles.sort(),
  };
}

function createLocalBackendHelperSigningIgnore({ appPath, existingIgnore, signableFiles }) {
  const helperRoot = path.resolve(getLocalBackendHelperRoot(appPath));
  const signableFileSet = new Set(signableFiles.map((filePath) => path.resolve(filePath)));

  return (filePath) => {
    if (shouldUseExistingIgnore(existingIgnore, filePath)) {
      return true;
    }

    const resolvedPath = path.resolve(filePath);
    if (!isPathInsideOrEqual(resolvedPath, helperRoot)) {
      return false;
    }

    const stat = assertNoSymlink(resolvedPath);
    if (!stat.isFile()) {
      return false;
    }

    return !signableFileSet.has(resolvedPath);
  };
}

function shouldUseExistingIgnore(existingIgnore, filePath) {
  if (!existingIgnore) {
    return false;
  }
  if (typeof existingIgnore === 'function') {
    return existingIgnore(filePath);
  }
  const ignoreRules = Array.isArray(existingIgnore) ? existingIgnore : [existingIgnore];
  return ignoreRules.some((rule) => {
    if (typeof rule === 'function') {
      return rule(filePath);
    }
    return Boolean(filePath.match(rule));
  });
}

module.exports = {
  HELPER_RUNTIME_RESOURCE_PATH,
  FAT_MACHO_MAGIC_BYTE_ORDER,
  MACHO_MAGIC_HEX_VALUES,
  MAX_REASONABLE_FAT_ARCHITECTURES,
  buildLocalBackendHelperSigningPlan,
  createLocalBackendHelperSigningIgnore,
  getLocalBackendHelperRoot,
  refreshSignedLocalBackendHelperManifest,
  isMachOFile,
  isPathInsideOrEqual,
  isReasonableFatMachOArchitectureCount,
};
