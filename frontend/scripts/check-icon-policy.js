/**
 * CI policy: lucide-react 以外のアイコン導入（react-icons等）と、独自SVGによるアイコン実装を禁止する。
 *
 * 例外:
 * - AgentOverlayShell.tsx の <svg> はフィルタ定義（アイコンではない）なので許可する。
 */

const fs = require('node:fs');
const path = require('node:path');

const FRONTEND_DIR = path.resolve(__dirname, '..');
const SRC_DIR = path.join(FRONTEND_DIR, 'src');

const ALLOW_INLINE_SVG = new Set([
  // SVGフィルタ定義（アイコン用途ではない）
  path.join(SRC_DIR, 'components', 'agent-overlay', 'AgentOverlayShell.tsx'),
]);

const FORBIDDEN_IMPORT_RE = [
  /from\s+['"]react-icons(?:\/[^'"]+)?['"]/,
  /from\s+['"]@heroicons\/react\/[^'"]+['"]/,
  /from\s+['"]@tabler\/icons-react['"]/,
  /from\s+['"]phosphor-react['"]/,
];

function walk(dir, out) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      walk(p, out);
    } else if (ent.isFile()) {
      if (p.endsWith('.ts') || p.endsWith('.tsx')) out.push(p);
    }
  }
}

function main() {
  const files = [];
  walk(SRC_DIR, files);

  const errors = [];

  for (const file of files) {
    const src = fs.readFileSync(file, 'utf8');

    for (const re of FORBIDDEN_IMPORT_RE) {
      if (re.test(src)) {
        errors.push(`[forbidden import] ${path.relative(FRONTEND_DIR, file)} matches ${re}`);
        break;
      }
    }

    // 独自SVG（特にアイコン）を禁止: 新規に <svg> を書かせない
    if (src.toLowerCase().includes('<svg') && !ALLOW_INLINE_SVG.has(file)) {
      errors.push(
        `[inline svg is forbidden] ${path.relative(FRONTEND_DIR, file)} contains <svg>. Use lucide-react instead.`
      );
    }
  }

  if (errors.length > 0) {
    console.error('Icon policy check failed:');
    for (const e of errors) console.error(`- ${e}`);
    process.exit(1);
  }

  console.log('Icon policy check passed.');
}

main();


