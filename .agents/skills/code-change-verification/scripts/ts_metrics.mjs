#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

const rootFlag = process.argv.indexOf("--repo-root");
const repoRoot = path.resolve(rootFlag >= 0 ? process.argv[rootFlag + 1] : process.cwd());
const webManifest = path.join(repoRoot, "apps", "web", "package.json");
if (!fs.existsSync(webManifest)) {
  fail(`apps/web/package.json not found below ${repoRoot}`);
}

const requireFromWeb = createRequire(webManifest);
let ts;
try {
  ts = requireFromWeb("typescript");
} catch (error) {
  fail(`could not load the existing apps/web TypeScript dependency: ${error.message}`);
}

let request;
try {
  let requestText = "";
  for await (const chunk of process.stdin) {
    requestText += chunk;
  }
  request = JSON.parse(requestText || "{}");
} catch (error) {
  fail(`invalid JSON request on stdin: ${error.message}`);
}

const suppliedSources =
  request.sources && typeof request.sources === "object" ? request.sources : null;
const files = suppliedSources
  ? Object.keys(suppliedSources).sort()
  : Array.isArray(request.files)
    ? request.files
    : [];
const ignoredTokenKinds = new Set([
  ts.SyntaxKind.EndOfFileToken,
  ts.SyntaxKind.WhitespaceTrivia,
  ts.SyntaxKind.NewLineTrivia,
  ts.SyntaxKind.SingleLineCommentTrivia,
  ts.SyntaxKind.MultiLineCommentTrivia,
  ts.SyntaxKind.ShebangTrivia,
  ts.SyntaxKind.ConflictMarkerTrivia,
]);

function normalise(relativePath) {
  return relativePath.split(path.sep).join("/");
}

function codeLines(sourceText, sourceFile) {
  const scanner = ts.createScanner(
    ts.ScriptTarget.Latest,
    false,
    sourceFile.languageVariant,
    sourceText,
  );
  const lines = new Set();
  for (let kind = scanner.scan(); kind !== ts.SyntaxKind.EndOfFileToken; kind = scanner.scan()) {
    if (ignoredTokenKinds.has(kind)) {
      continue;
    }
    const start = scanner.getTokenPos();
    const end = Math.max(start, scanner.getTextPos() - 1);
    const first = sourceFile.getLineAndCharacterOfPosition(start).line + 1;
    const last = sourceFile.getLineAndCharacterOfPosition(end).line + 1;
    for (let line = first; line <= last; line += 1) {
      lines.add(line);
    }
  }
  return lines;
}

function isFunctionLike(node) {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isConstructorDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node)
  );
}

function textName(name, sourceFile) {
  if (!name) {
    return null;
  }
  if (ts.isIdentifier(name) || ts.isPrivateIdentifier(name)) {
    return name.text;
  }
  if (ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  return name.getText(sourceFile);
}

function functionName(node, sourceFile, anonymousIndex) {
  const ownName = textName(node.name, sourceFile);
  if (ownName) {
    return ownName;
  }
  if (ts.isConstructorDeclaration(node)) {
    return "constructor";
  }
  const parent = node.parent;
  if (parent && ts.isVariableDeclaration(parent)) {
    return textName(parent.name, sourceFile);
  }
  if (parent && ts.isPropertyAssignment(parent)) {
    return textName(parent.name, sourceFile);
  }
  if (parent && ts.isPropertyDeclaration(parent)) {
    return textName(parent.name, sourceFile);
  }
  return `<callback:${anonymousIndex}>`;
}

function complexityOf(root) {
  let complexity = 1;
  function visit(node) {
    if (node !== root && isFunctionLike(node)) {
      return;
    }
    if (
      ts.isIfStatement(node) ||
      ts.isForStatement(node) ||
      ts.isForInStatement(node) ||
      ts.isForOfStatement(node) ||
      ts.isWhileStatement(node) ||
      ts.isDoStatement(node) ||
      ts.isCatchClause(node) ||
      ts.isConditionalExpression(node)
    ) {
      complexity += 1;
    } else if (ts.isCaseClause(node)) {
      complexity += 1;
    } else if (
      ts.isBinaryExpression(node) &&
      [
        ts.SyntaxKind.AmpersandAmpersandToken,
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.QuestionQuestionToken,
        ts.SyntaxKind.AmpersandAmpersandEqualsToken,
        ts.SyntaxKind.BarBarEqualsToken,
        ts.SyntaxKind.QuestionQuestionEqualsToken,
      ].includes(node.operatorToken.kind)
    ) {
      complexity += 1;
    }
    ts.forEachChild(node, visit);
  }
  ts.forEachChild(root, visit);
  return complexity;
}

function nestingOf(root) {
  let maximum = 0;
  function visit(node, depth) {
    if (node !== root && isFunctionLike(node)) {
      return;
    }
    const control =
      ts.isIfStatement(node) ||
      ts.isForStatement(node) ||
      ts.isForInStatement(node) ||
      ts.isForOfStatement(node) ||
      ts.isWhileStatement(node) ||
      ts.isDoStatement(node) ||
      ts.isTryStatement(node) ||
      ts.isCatchClause(node) ||
      ts.isWithStatement(node) ||
      ts.isSwitchStatement(node);
    const childDepth = control ? depth + 1 : depth;
    maximum = Math.max(maximum, childDepth);
    ts.forEachChild(node, (child) => visit(child, childDepth));
  }
  ts.forEachChild(root, (child) => visit(child, 0));
  return maximum;
}

function importSpecifiers(sourceFile) {
  const imports = [];
  function visit(node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      imports.push(node.moduleSpecifier.text);
    } else if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference) &&
      node.moduleReference.expression &&
      ts.isStringLiteral(node.moduleReference.expression)
    ) {
      imports.push(node.moduleReference.expression.text);
    } else if (
      ts.isCallExpression(node) &&
      node.arguments.length === 1 &&
      ts.isStringLiteral(node.arguments[0]) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.expression) && node.expression.text === "require"))
    ) {
      imports.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return [...new Set(imports)].sort();
}

function analyse(relativePath) {
  const absolutePath = path.join(repoRoot, relativePath);
  const sourceText = suppliedSources
    ? suppliedSources[relativePath]
    : fs.readFileSync(absolutePath, "utf8");
  const scriptKind = relativePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(
    relativePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
  const lines = codeLines(sourceText, sourceFile);
  const functions = [];
  const anonymousByScope = new Map();

  function walk(node, scope) {
    let nextScope = scope;
    if (
      (ts.isClassDeclaration(node) || ts.isClassExpression(node)) &&
      node.name &&
      node.name.text
    ) {
      nextScope = [...scope, node.name.text];
    }
    if (isFunctionLike(node)) {
      const scopeKey = scope.join(".") || "<file>";
      const nextAnonymous = (anonymousByScope.get(scopeKey) || 0) + 1;
      anonymousByScope.set(scopeKey, nextAnonymous);
      const localName = functionName(node, sourceFile, nextAnonymous);
      const symbol = [...scope, localName].join(".");
      const start = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
      const end = sourceFile.getLineAndCharacterOfPosition(
        Math.max(node.getStart(), node.end - 1),
      ).line + 1;
      let effectiveLines = 0;
      for (let line = start; line <= end; line += 1) {
        if (lines.has(line)) {
          effectiveLines += 1;
        }
      }
      functions.push({
        symbol,
        effective_lines: effectiveLines,
        cyclomatic_complexity: complexityOf(node),
        nesting_depth: nestingOf(node),
      });
      nextScope = [...scope, localName];
    }
    ts.forEachChild(node, (child) => walk(child, nextScope));
  }
  walk(sourceFile, []);

  return {
    path: normalise(relativePath),
    effective_lines: lines.size,
    functions,
    imports: importSpecifiers(sourceFile),
    diagnostics: sourceFile.parseDiagnostics.map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
    ),
  };
}

process.stdout.write(`${JSON.stringify({ files: files.map((file) => analyse(file)) })}\n`);
