#!/usr/bin/env node
/**
 * Static HTML site translator (Chinese -> English) powered by Youdao OpenAPI V3.
 *
 * No npm dependencies are required. It translates only static visible text and
 * selected text attributes, while keeping Vue templates, scripts, styles and
 * data files untouched.
 */
import { createHash, randomUUID } from 'node:crypto';
import { access, mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const DEFAULT_EXCLUDED_DIRS = new Set([
  '.git', '.idea', '.omc', '.sass-cache', 'node_modules', 'jsonDatas', 'tools',
]);
const TEXT_ATTRIBUTES = new Set(['title', 'alt', 'placeholder', 'aria-label']);
const URL_ATTRIBUTES = new Set(['src', 'href', 'poster', 'srcset']);
const SKIPPED_TAGS = new Set(['script', 'style', 'template']);
const CHINESE_RE = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
const ONLY_WHITESPACE_RE = /^\s*$/;
const DEFAULT_REQUEST_INTERVAL_MS = 600;
const DEFAULT_MAX_RETRIES = 4;
const DEFAULT_RETRY_BASE_DELAY_MS = 1000;

function printHelp() {
  console.log(`
用法：
  node translate-site.mjs --source <源目录> --output <英文输出目录> --config <有道配置文件> [选项]

必填参数：
  --source <dir>       中文站所在目录，例如 .
  --output <dir>       英文页面输出目录，例如 .\\en
  --config <file>      有道配置 JSON，例如 .\\tools\\site-translator\\youdao.config.json

可选参数：
  --dry-run            只扫描与统计，不调用 API、不写入页面
  --force               忽略翻译缓存，重新请求所有静态中文文本
  --help, -h            显示此帮助

示例：
  node .\\tools\\site-translator\\translate-site.mjs --source . --output .\\en --config .\\tools\\site-translator\\youdao.config.json --dry-run
  node .\\tools\\site-translator\\translate-site.mjs --source . --output .\\en --config .\\tools\\site-translator\\youdao.config.json
`);
}

function parseArgs(argv) {
  const options = { dryRun: false, force: false };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === '--help' || token === '-h') {
      options.help = true;
      continue;
    }
    if (token === '--dry-run') {
      options.dryRun = true;
      continue;
    }
    if (token === '--force') {
      options.force = true;
      continue;
    }
    if (['--source', '--output', '--config'].includes(token)) {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) {
        throw new Error(`${token} 缺少参数值。`);
      }
      options[token.slice(2)] = value;
      index += 1;
      continue;
    }
    throw new Error(`不支持的参数：${token}`);
  }
  return options;
}

function toAbsolutePath(value) {
  return path.resolve(process.cwd(), value);
}

async function pathExists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function listFilesByExtension(rootDir, extension) {
  if (!(await pathExists(rootDir))) {
    return [];
  }
  const files = [];

  async function walk(currentDir) {
    const entries = await readdir(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      const absolutePath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        await walk(absolutePath);
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith(extension)) {
        files.push(absolutePath);
      }
    }
  }

  await walk(rootDir);
  return files.sort((left, right) => left.localeCompare(right));
}

async function listHtmlFiles(rootDir, outputDir) {
  const files = [];
  const outputRelative = path.relative(rootDir, outputDir);
  const outputTopLevel = outputRelative && !outputRelative.startsWith('..')
    ? outputRelative.split(path.sep)[0]
    : null;

  async function walk(currentDir) {
    const entries = await readdir(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      const absolutePath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        if (DEFAULT_EXCLUDED_DIRS.has(entry.name) || entry.name === outputTopLevel) {
          continue;
        }
        await walk(absolutePath);
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.html')) {
        files.push(absolutePath);
      }
    }
  }

  await walk(rootDir);
  return files.sort((left, right) => left.localeCompare(right));
}

function truncateForYoudao(text) {
  return text.length <= 20 ? text : `${text.slice(0, 10)}${text.length}${text.slice(-10)}`;
}

function createYoudaoSign({ appKey, appSecret, q, salt, curtime }) {
  return createHash('sha256')
    .update(`${appKey}${truncateForYoudao(q)}${salt}${curtime}${appSecret}`)
    .digest('hex');
}

function readNonNegativeInteger(value, fallback, fieldName) {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`配置项 ${fieldName} 必须是大于或等于 0 的整数。`);
  }
  return value;
}

async function loadConfig(configPath) {
  let config;
  try {
    config = JSON.parse(await readFile(configPath, 'utf8'));
  } catch (error) {
    throw new Error(`无法读取配置文件 ${configPath}：${error.message}`);
  }

  if (!config.appKey || !config.appSecret) {
    throw new Error('有道配置必须包含 appKey 与 appSecret。请复制配置模板后填写真实值。');
  }

  return {
    appKey: String(config.appKey),
    appSecret: String(config.appSecret),
    from: config.from || 'zh-CHS',
    to: config.to || 'en',
    endpoint: config.endpoint || 'https://openapi.youdao.com/api',
    requestIntervalMs: readNonNegativeInteger(
      config.requestIntervalMs,
      DEFAULT_REQUEST_INTERVAL_MS,
      'requestIntervalMs',
    ),
    maxRetries: readNonNegativeInteger(config.maxRetries, DEFAULT_MAX_RETRIES, 'maxRetries'),
    retryBaseDelayMs: readNonNegativeInteger(
      config.retryBaseDelayMs,
      DEFAULT_RETRY_BASE_DELAY_MS,
      'retryBaseDelayMs',
    ),
  };
}

async function loadCache(cachePath) {
  if (!(await pathExists(cachePath))) {
    return {};
  }
  try {
    const cache = JSON.parse(await readFile(cachePath, 'utf8'));
    return cache && typeof cache === 'object' && !Array.isArray(cache) ? cache : {};
  } catch {
    console.warn(`警告：翻译缓存无法解析，将新建缓存：${cachePath}`);
    return {};
  }
}

async function saveJsonAtomically(targetPath, payload) {
  await mkdir(path.dirname(targetPath), { recursive: true });
  const temporaryPath = `${targetPath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  await rename(temporaryPath, targetPath);
}

async function translateWithYoudao(text, config) {
  const salt = randomUUID().replaceAll('-', '');
  const curtime = Math.floor(Date.now() / 1000).toString();
  const sign = createYoudaoSign({ ...config, q: text, salt, curtime });
  const body = new URLSearchParams({
    q: text,
    from: config.from,
    to: config.to,
    appKey: config.appKey,
    salt,
    sign,
    signType: 'v3',
    curtime,
  });

  let response;
  try {
    response = await fetch(config.endpoint, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body,
    });
  } catch (error) {
    throw new Error(`请求有道翻译 API 失败：${error.message}`);
  }

  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(`有道翻译 API 返回了无法解析的响应（HTTP ${response.status}）。`);
  }

  if (!response.ok || result.errorCode !== '0' || !Array.isArray(result.translation)) {
    const message = result.errorCode ? `errorCode=${result.errorCode}` : `HTTP ${response.status}`;
    const error = new Error(`有道翻译失败（${message}）：${JSON.stringify(result)}`);
    error.youdaoErrorCode = result.errorCode ? String(result.errorCode) : null;
    throw error;
  }

  return result.translation.join('');
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForRequestSlot(requestState, requestIntervalMs) {
  const elapsed = Date.now() - requestState.lastRequestAt;
  const remaining = Math.max(0, requestIntervalMs - elapsed);
  if (remaining > 0) {
    await sleep(remaining);
  }
  requestState.lastRequestAt = Date.now();
  requestState.requestCount += 1;
}

async function translateWithRetry(text, config, requestState) {
  for (let retryIndex = 0; ; retryIndex += 1) {
    await waitForRequestSlot(requestState, config.requestIntervalMs);
    try {
      return await translateWithYoudao(text, config);
    } catch (error) {
      const shouldRetry = error.youdaoErrorCode === '411' && retryIndex < config.maxRetries;
      if (!shouldRetry) {
        throw error;
      }
      const delay = config.retryBaseDelayMs * (2 ** retryIndex);
      console.warn(
        `有道返回 411（请求受限），将在 ${delay}ms 后重试：第 ${retryIndex + 1}/${config.maxRetries} 次。`,
      );
      await sleep(delay);
    }
  }
}

function isVueExpression(value) {
  return /{{[\s\S]*?}}/.test(value) || /^\s*(?:[:@]|v-)/.test(value);
}

function shouldTranslateText(value) {
  const trimmed = value.trim();
  return Boolean(trimmed) && CHINESE_RE.test(trimmed) && !isVueExpression(trimmed);
}

function preserveOuterWhitespace(value, translated) {
  const leading = value.match(/^\s*/)?.[0] || '';
  const trailing = value.match(/\s*$/)?.[0] || '';
  return leading + translated + trailing;
}

function forEachStaticTextFragment(value, callback) {
  const fragments = value.split(/(\{\{[\s\S]*?\}\})/g);
  for (let index = 0; index < fragments.length; index += 2) {
    callback(fragments[index], index, fragments);
  }
}

function translateStaticTextFragments(value, translations) {
  let transformed = value;
  const fragments = value.split(/(\{\{[\s\S]*?\}\})/g);
  for (let index = 0; index < fragments.length; index += 2) {
    const fragment = fragments[index];
    if (!shouldTranslateText(fragment)) continue;
    const translated = translations.get(fragment.trim());
    if (translated) {
      fragments[index] = preserveOuterWhitespace(fragment, translated);
    }
  }
  if (fragments.length > 1) {
    transformed = fragments.join('');
  }
  return transformed;
}
function isExternalOrSpecialUrl(value) {
  const trimmed = value.trim();
  return !trimmed
    || trimmed.startsWith('#')
    || trimmed.startsWith('//')
    || /^(?:[a-z][a-z\d+.-]*:|data:|mailto:|tel:)/i.test(trimmed)
    || trimmed.includes('{{')
    || trimmed.includes('}}');
}

function rebaseUrl(url, sourceFilePath, sourceRoot, outputRoot, outputFilePath) {
  if (isExternalOrSpecialUrl(url)) {
    return url;
  }

  const [, pathPart = '', suffix = ''] = url.match(/^([^?#]*)([\s\S]*)$/) || [];
  if (!pathPart || pathPart.startsWith('/')) {
    return url;
  }

  const sourceAssetPath = path.resolve(path.dirname(sourceFilePath), pathPart);
  const relativeToRoot = path.relative(sourceRoot, sourceAssetPath);
  if (relativeToRoot.startsWith('..') || path.isAbsolute(relativeToRoot)) {
    return url;
  }

  const isHtmlPage = /\.html?$/i.test(pathPart);
  const isComponentScript = /\.js$/i.test(pathPart)
    && relativeToRoot.split(path.sep)[0].toLowerCase() === 'components';
  const targetPath = isHtmlPage || isComponentScript
    ? path.join(outputRoot, relativeToRoot)
    : sourceAssetPath;
  let rebased = path.relative(path.dirname(outputFilePath), targetPath).split(path.sep).join('/');
  if (!rebased.startsWith('.')) {
    rebased = `./${rebased}`;
  }
  return `${rebased}${suffix}`;
}

function rebaseSrcset(value, sourceFilePath, sourceRoot, outputRoot, outputFilePath) {
  return value.split(',').map((item) => {
    const part = item.trim();
    if (!part) return item;
    const [url, ...descriptor] = part.split(/\s+/);
    return [rebaseUrl(url, sourceFilePath, sourceRoot, outputRoot, outputFilePath), ...descriptor].join(' ');
  }).join(', ');
}

function replaceHtmlLang(html) {
  return html.replace(/<html\b([^>]*)>/i, (tag, attrs) => {
    if (/\blang\s*=/.test(attrs)) {
      return `<html${attrs.replace(/\blang\s*=\s*(["'])[^"']*\1/i, 'lang="en"')}>`;
    }
    return `<html${attrs} lang="en">`;
  });
}

const HTML_TAG_RE = /<(?:"[^"]*"|'[^']*'|[^'">])*>/g;

function splitHtmlByTags(html) {
  const parts = [];
  let cursor = 0;
  for (const match of html.matchAll(HTML_TAG_RE)) {
    parts.push(html.slice(cursor, match.index), match[0]);
    cursor = match.index + match[0].length;
  }
  parts.push(html.slice(cursor));
  return parts;
}

function protectNonTranslatableContent(html, { protectTemplateTags = true } = {}) {
  const protectedBlocks = [];
  const protectedTagNames = protectTemplateTags ? 'script|style|template' : 'script|style';
  const protectedTagRe = new RegExp('<(' + protectedTagNames + ')\\b([^>]*)>([\\s\\S]*?)<\\/\\1\\s*>', 'gi');
  let protectedHtml = html.replace(protectedTagRe, (_, tagName, attributes, content) => {
    const token = '___SITE_TRANSLATOR_PROTECTED_' + protectedBlocks.length + '___';
    protectedBlocks.push(content);
    return '<' + tagName + attributes + '>' + token + '</' + tagName + '>';
  });

  protectedHtml = protectedHtml.replace(/<!--[\s\S]*?-->/g, (comment) => {
    const token = '___SITE_TRANSLATOR_PROTECTED_' + protectedBlocks.length + '___';
    protectedBlocks.push(comment);
    return token;
  });

  return {
    html: protectedHtml,
    restore(value) {
      return value.replace(/___SITE_TRANSLATOR_PROTECTED_(\d+)___/g, (_, index) => protectedBlocks[Number(index)]);
    },
  };
}

function collectTranslationCandidates(html, options) {
  const candidates = new Set();
  const { html: protectedHtml } = protectNonTranslatableContent(html, options);

  const attrRe = /\s([:\w-]+)(\s*=\s*)(["'])([\s\S]*?)\3/g;
  let attrMatch;
  while ((attrMatch = attrRe.exec(protectedHtml))) {
    const [, name, , , value] = attrMatch;
    if (TEXT_ATTRIBUTES.has(name.toLowerCase()) && shouldTranslateText(value)) {
      candidates.add(value.trim());
    }
  }

  const textParts = splitHtmlByTags(protectedHtml);
  for (let index = 0; index < textParts.length; index += 2) {
    const text = textParts[index];
    if (!text || ONLY_WHITESPACE_RE.test(text)) continue;
    forEachStaticTextFragment(text, (fragment) => {
      if (shouldTranslateText(fragment)) {
        candidates.add(fragment.trim());
      }
    });
  }
  return [...candidates];
}

function transformHtml(html, context, translations) {
  const protectedContent = protectNonTranslatableContent(html, {
    protectTemplateTags: context.protectTemplateTags !== false,
  });
  let transformed = protectedContent.html;

  transformed = replaceHtmlLang(transformed);
  transformed = transformed.replace(/\s([:\w-]+)(\s*=\s*)(["'])([\s\S]*?)\3/g, (whole, name, equals, quote, value) => {
    const normalizedName = name.toLowerCase();
    if (TEXT_ATTRIBUTES.has(normalizedName) && shouldTranslateText(value)) {
      const translated = translations.get(value.trim());
      return translated ? ` ${name}${equals}${quote}${preserveOuterWhitespace(value, translated)}${quote}` : whole;
    }
    if (URL_ATTRIBUTES.has(normalizedName) && !isVueExpression(value)) {
      const rebased = normalizedName === 'srcset'
        ? rebaseSrcset(value, context.sourceFilePath, context.sourceRoot, context.outputRoot, context.outputFilePath)
        : rebaseUrl(value, context.sourceFilePath, context.sourceRoot, context.outputRoot, context.outputFilePath);
      return ` ${name}${equals}${quote}${rebased}${quote}`;
    }
    return whole;
  });

  const parts = splitHtmlByTags(transformed);
  for (let index = 0; index < parts.length; index += 2) {
    const text = parts[index];
    if (!text) continue;
    parts[index] = translateStaticTextFragments(text, translations);
  }
  transformed = parts.join('');

  return protectedContent.restore(transformed);
}

function collectComponentTranslationCandidates(source) {
  const candidates = new Set();
  const templateRe = /template\s*:\s*`([\s\S]*?)`/g;
  const defaultTextRe = /default\s*:\s*(['"])([^'"\r\n]*?)\1/g;
  let match;

  while ((match = templateRe.exec(source))) {
    for (const candidate of collectTranslationCandidates(match[1], { protectTemplateTags: false })) {
      candidates.add(candidate);
    }
  }
  while ((match = defaultTextRe.exec(source))) {
    if (shouldTranslateText(match[2])) {
      candidates.add(match[2].trim());
    }
  }
  return [...candidates];
}

function transformComponentSource(source, context, translations) {
  let transformed = source.replace(/template\s*:\s*`([\s\S]*?)`/g, (whole, template) => {
    return whole.replace(template, transformHtml(template, { ...context, protectTemplateTags: false }, translations));
  });

  transformed = transformed.replace(/(default\s*:\s*)(['"])([^'"\r\n]*?)\2/g, (whole, prefix, quote, value) => {
    if (!shouldTranslateText(value)) {
      return whole;
    }
    const translated = translations.get(value.trim());
    return translated ? `${prefix}${quote}${preserveOuterWhitespace(value, translated)}${quote}` : whole;
  });

  return transformed;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }
  if (!options.source || !options.output || !options.config) {
    printHelp();
    throw new Error('缺少 --source、--output 或 --config 参数。');
  }

  const sourceRoot = toAbsolutePath(options.source);
  const outputRoot = toAbsolutePath(options.output);
  const configPath = toAbsolutePath(options.config);
  if (sourceRoot === outputRoot) {
    throw new Error('--output 不能与 --source 相同，否则会覆盖中文站。');
  }
  if (!(await pathExists(sourceRoot))) {
    throw new Error(`源目录不存在：${sourceRoot}`);
  }
  if (!options.dryRun && !(await pathExists(configPath))) {
    throw new Error(`配置文件不存在：${configPath}`);
  }

  const htmlFiles = await listHtmlFiles(sourceRoot, outputRoot);
  if (!htmlFiles.length) {
    throw new Error(`源目录中没有找到 HTML 文件：${sourceRoot}`);
  }

  const sourceEntries = [];
  const componentEntries = [];
  const candidateSet = new Set();
  for (const sourceFilePath of htmlFiles) {
    const html = await readFile(sourceFilePath, 'utf8');
    sourceEntries.push({ sourceFilePath, html });
    for (const candidate of collectTranslationCandidates(html)) {
      candidateSet.add(candidate);
    }
  }

  const componentFiles = await listFilesByExtension(path.join(sourceRoot, 'components'), '.js');
  for (const sourceFilePath of componentFiles) {
    const source = await readFile(sourceFilePath, 'utf8');
    componentEntries.push({ sourceFilePath, source });
    for (const candidate of collectComponentTranslationCandidates(source)) {
      candidateSet.add(candidate);
    }
  }

  console.log(`扫描完成：发现 ${htmlFiles.length} 个 HTML 文件、${componentFiles.length} 个组件文件，待翻译静态中文文本 ${candidateSet.size} 条。`);
  console.log('已跳过：script/style/template 逻辑、HTML 注释、Vue 插值/指令、jsonDatas 目录；组件仅翻译模板可见文案和 default 文案。');

  if (options.dryRun) {
    console.log('Dry run 完成：未请求有道 API，未写入任何英文页面。');
    return;
  }

  const config = await loadConfig(configPath);
  const cachePath = path.join(path.dirname(configPath), '.translation-cache.json');
  const cache = await loadCache(cachePath);
  const translations = new Map();
  const requestState = { lastRequestAt: 0, requestCount: 0 };
  let translatedTextCount = 0;

  for (const text of candidateSet) {
    const cacheKey = `${config.from}->${config.to}:${text}`;
    if (!options.force && typeof cache[cacheKey] === 'string' && cache[cacheKey]) {
      translations.set(text, cache[cacheKey]);
      continue;
    }
    console.log(`翻译 ${translatedTextCount + 1}/${candidateSet.size}：${text}`);
    const translated = await translateWithRetry(text, config, requestState);
    translations.set(text, translated);
    cache[cacheKey] = translated;
    await saveJsonAtomically(cachePath, cache);
    translatedTextCount += 1;
  }

  for (const entry of sourceEntries) {
    const relativePath = path.relative(sourceRoot, entry.sourceFilePath);
    const outputFilePath = path.join(outputRoot, relativePath);
    const outputHtml = transformHtml(entry.html, {
      sourceRoot,
      outputRoot,
      sourceFilePath: entry.sourceFilePath,
      outputFilePath,
    }, translations);
    await mkdir(path.dirname(outputFilePath), { recursive: true });
    await writeFile(outputFilePath, outputHtml, 'utf8');
  }

  for (const entry of componentEntries) {
    const relativePath = path.relative(sourceRoot, entry.sourceFilePath);
    const outputFilePath = path.join(outputRoot, relativePath);
    const outputSource = transformComponentSource(entry.source, {
      sourceRoot,
      outputRoot,
      // 组件模板会注入英文页面；本项目页面均在站点根目录，故按根页面计算静态资源回指路径。
      sourceFilePath: path.join(sourceRoot, 'index.html'),
      outputFilePath: path.join(outputRoot, 'index.html'),
    }, translations);
    await mkdir(path.dirname(outputFilePath), { recursive: true });
    await writeFile(outputFilePath, outputSource, 'utf8');
  }

  console.log(`生成完成：${htmlFiles.length} 个英文页面和 ${componentFiles.length} 个英文组件已写入 ${outputRoot}`);
  console.log(`本次实际调用有道 API：${requestState.requestCount} 次；缓存文件：${cachePath}`);
}

main().catch((error) => {
  console.error(`\n翻译工具执行失败：${error.message}`);
  process.exitCode = 1;
});







