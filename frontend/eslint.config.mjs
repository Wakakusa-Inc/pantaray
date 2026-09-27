// eslint.config.mjs - ESM 形式の設定ファイル
import globals from 'globals';
import pluginJs from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactPlugin from 'eslint-plugin-react';
import pluginReactConfig from 'eslint-plugin-react/configs/recommended.js';
import pluginReactJsxRuntimeConfig from 'eslint-plugin-react/configs/jsx-runtime.js';
import pluginReactHooks from 'eslint-plugin-react-hooks';
import pluginReactRefresh from 'eslint-plugin-react-refresh';
import pluginPrettier from 'eslint-plugin-prettier';
import configPrettier from 'eslint-config-prettier';

export default tseslint.config(
  // Global ignores - Should be the first element
  {
    ignores: [
      'dist/',
      'node_modules/',
      'build/',
      'release/',
      '.cache/',
      '.generated/',
      '.vite/',
      '.next/',
      // Electron:
      // - legacy JS は段階移行中のため lint 対象外（electron/src のみ lint する）
      'electron/*.js',
      'electron/dist/',
      'electron/native/',
      'electron/resources/local_backend_helper/',
      'electron/*.json',
      '*.config.js',
      '*.config.cjs',
      '*.config.mjs',
      '.eslintrc.cjs',
      'vite.config.ts',
    ],
  },

  // Base ESLint recommended rules
  pluginJs.configs.recommended,

  // Base TypeScript recommended rules for all TS/TSX
  ...tseslint.configs.recommended,

  // React base recommended config - Apply settings and languageOptions separately
  {
    files: ['src/**/*.{ts,tsx}'],
    // Explicitly define the React plugin
    plugins: {
      react: reactPlugin,
    },
    // Apply settings from pluginReactConfig here
    settings: pluginReactConfig.settings || { react: { version: 'detect' } },
    // Apply languageOptions from pluginReactConfig here
    languageOptions: {
      ...pluginReactConfig.languageOptions,
      parserOptions: {
        ...pluginReactConfig.languageOptions?.parserOptions,
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.es2020,
      },
    },
    // Apply rules from pluginReactConfig here
    rules: {
      ...pluginReactConfig.rules,
      'react/prop-types': 'off', // Specific overrides
    },
  },

  // React JSX runtime config
  // pluginReactJsxRuntimeConfig might just be rules, apply them correctly
  {
    files: ['src/**/*.{ts,tsx}'],
    // Explicitly define the React plugin
    plugins: {
      react: reactPlugin,
    },
    rules: pluginReactJsxRuntimeConfig.rules,
  },

  // React Hooks config
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': pluginReactHooks,
    },
    rules: pluginReactHooks.configs.recommended.rules,
  },

  // React Refresh config
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-refresh': pluginReactRefresh,
    },
    rules: {
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },

  // Custom rules and Prettier plugin for source files
  {
    files: ['src/**/*.{ts,tsx}', 'electron/src/**/*.{ts,tsx}'],
    plugins: {
      prettier: pluginPrettier,
    },
    rules: {
      // 既存コードに Any が残っているため、段階的に改善する（CIブロックはしない）
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      'prettier/prettier': 'warn',
    },
  },

  // Node.js scripts / CommonJS modules
  {
    files: [
      'scripts/**/*.{js,cjs,mjs}',
      'shared/**/*.{js,cjs,mjs}',
      'electron/preload/**/*.{js,cjs,mjs}',
    ],
    languageOptions: {
      sourceType: 'commonjs',
      globals: {
        ...globals.node,
        ...globals.es2020,
        // Nodeでも利用可能な標準組み込み（eslint の globals 定義に無いケースがある）
        URL: 'readonly',
      },
    },
    rules: {
      '@typescript-eslint/no-require-imports': 'off',
    },
  },

  // Electron(main) TypeScript (node runtime)
  {
    files: ['electron/src/**/*.{ts,tsx}'],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.es2020,
      },
    },
  },

  // Config for vite.config.ts
  {
    files: ['vite.config.ts'],
    languageOptions: {
      sourceType: 'module',
      globals: {
        ...globals.node,
      },
    },
  },

  // Config for node-based tests (node:test)
  {
    files: ['tests/**/*.{js,cjs,mjs,ts,tsx}'],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.es2020,
      },
    },
    rules: {
      // tests では CommonJS の require を許可する（node:test を軽量に使うため）
      '@typescript-eslint/no-require-imports': 'off',
      // テストでは意図的に未使用の引数を置くことが多い（モック/インターフェース互換など）
      // `_` prefix は「未使用」を明示するため許可する。
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
    },
  },

  // Prettier config to disable conflicting rules - MUST BE LAST
  configPrettier
);
