/**
 * ESLint configuration.
 *
 * Aggressive on purpose: `npm run lint` passes --max-warnings 0, so anything
 * reported here blocks a commit. Rules are chosen to catch real defects
 * (missing hook dependencies, unreachable code, accessibility mistakes) rather
 * than to enforce style — style is prettier's job.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:react/recommended",
    "plugin:react/jsx-runtime",
    "plugin:react-hooks/recommended",
    "plugin:jsx-a11y/recommended",
  ],
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: "18.3" } },
  // dist-coverage is the instrumented bundle the Playwright harness builds;
  // it is generated output like dist, just under its own name so a test run
  // cannot overwrite the bundle `make start` serves.
  ignorePatterns: [
    "dist",
    "dist-coverage",
    "node_modules",
    "coverage",
    ".nyc_output",
    "*.config.js",
  ],
  rules: {
    // --- Correctness ---
    "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    "no-console": ["warn", { allow: ["warn", "error"] }],
    "no-debugger": "error",
    "no-alert": "error",
    eqeqeq: ["error", "always", { null: "ignore" }],
    "no-var": "error",
    "prefer-const": "error",
    "no-shadow": "error",
    "no-return-await": "error",
    "require-await": "error",
    "no-promise-executor-return": "error",
    "no-unreachable-loop": "error",
    "no-constant-binary-expression": "error",
    "no-self-compare": "error",
    "array-callback-return": "error",
    "consistent-return": "error",

    // --- React ---
    // A missing dependency is a stale-closure bug waiting to happen, so this is
    // an error rather than the default warning.
    "react-hooks/exhaustive-deps": "error",
    "react/jsx-key": ["error", { checkFragmentShorthand: true }],
    "react/no-unstable-nested-components": "error",
    "react/no-array-index-key": "warn",
    "react/self-closing-comp": "error",
    "react/jsx-no-target-blank": ["error", { enforceDynamicLinks: "always" }],
    // PropTypes are not used; the app is small and consistently structured.
    "react/prop-types": "off",

    // --- Accessibility ---
    "jsx-a11y/no-autofocus": "off", // the sign-in field legitimately autofocuses
    "jsx-a11y/label-has-associated-control": [
      "error",
      { assert: "either" }, // wrapping or htmlFor both acceptable
    ],
  },
  overrides: [
    {
      files: ["tests/**/*.mjs", "tests/**/*.js"],
      env: { node: true },
      rules: { "no-console": "off" },
    },
  ],
};
