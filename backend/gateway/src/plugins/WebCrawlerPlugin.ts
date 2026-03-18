import axios from 'axios';
import { JSDOM } from 'jsdom';
import { Readability } from '@mozilla/readability';
import { chromium } from 'playwright';
import robotsParser from 'robots-parser';
import { IPlugin, PluginParams, PluginResult } from './IPlugin';
import { config, blockedDomains } from '../config';
import { logger } from '../utils/logger';

interface CrawlParams extends PluginParams {
  url: string;
}

interface CacheEntry {
  content: string;
  cachedAt: number;
}

export class WebCrawlerPlugin implements IPlugin {
  id = 'web-crawler';
  private cache: Map<string, CacheEntry> = new Map();

  async execute(params: PluginParams): Promise<PluginResult> {
    const { url, trace_id } = params as CrawlParams;

    // Task 7.4 – domain blacklist
    try {
      const parsed = new URL(url);
      if (blockedDomains.has(parsed.hostname)) {
        return { type: 'crawl_result', plugin: this.id, error: 'domain_blocked' };
      }
    } catch {
      return { type: 'crawl_result', plugin: this.id, error: 'invalid_url' };
    }

    // Task 7.5 – URL cache
    const cached = this.cache.get(url);
    if (cached) {
      const ageMins = (Date.now() - cached.cachedAt) / 60000;
      if (ageMins < config.CRAWLER_CACHE_TTL_MIN) {
        logger.info({ event: 'crawl_cache_hit', url, trace_id });
        return { type: 'crawl_result', plugin: this.id, content: cached.content };
      }
    }

    // Task 7.3 – robots.txt check
    if (!config.CRAWLER_IGNORE_ROBOTS) {
      const allowed = await this.checkRobots(url);
      if (!allowed) {
        logger.warn({ event: 'crawl_robots_disallowed', url, trace_id });
        return { type: 'crawl_result', plugin: this.id, error: 'robots_disallowed' };
      }
    }

    // Task 7.1 – primary HTTP + Readability crawl
    let content = await this.crawlHttp(url, trace_id);

    // Task 7.2 – Playwright fallback if content too short
    if (content.length < 100) {
      logger.info({ event: 'crawl_playwright_fallback', url, trace_id });
      content = await this.crawlPlaywright(url, trace_id);
    }

    if (!content) {
      return { type: 'crawl_result', plugin: this.id, error: 'crawl_failed' };
    }

    // Cache result
    this.cache.set(url, { content, cachedAt: Date.now() });

    logger.info({ event: 'crawl_success', url, trace_id, word_count: content.split(' ').length });
    return {
      type: 'crawl_result',
      plugin: this.id,
      content,
      metadata: { url, word_count: content.split(' ').length },
    };
  }

  private async crawlHttp(url: string, traceId: string): Promise<string> {
    try {
      const response = await axios.get<string>(url, {
        timeout: config.CRAWLER_TIMEOUT_MS,
        headers: { 'User-Agent': 'openVman-gateway/1.0 (+https://github.com/openVman)' },
      });
      const dom = new JSDOM(response.data, { url });
      const reader = new Readability(dom.window.document);
      const article = reader.parse();
      return article?.textContent?.trim() ?? '';
    } catch (err) {
      logger.warn({ event: 'crawl_http_failed', url, traceId, err });
      return '';
    }
  }

  private async crawlPlaywright(url: string, traceId: string): Promise<string> {
    let browser;
    try {
      browser = await chromium.launch({ headless: true });
      const page = await browser.newPage();
      await page.goto(url, { timeout: config.CRAWLER_TIMEOUT_MS, waitUntil: 'networkidle' });
      const html = await page.content();
      const dom = new JSDOM(html, { url });
      const reader = new Readability(dom.window.document);
      const article = reader.parse();
      return article?.textContent?.trim() ?? '';
    } catch (err) {
      logger.warn({ event: 'crawl_playwright_failed', url, traceId, err });
      return '';
    } finally {
      await browser?.close();
    }
  }

  private async checkRobots(url: string): Promise<boolean> {
    try {
      const parsed = new URL(url);
      const robotsUrl = `${parsed.protocol}//${parsed.host}/robots.txt`;
      const response = await axios.get<string>(robotsUrl, { timeout: 3000 });
      const robots = robotsParser(robotsUrl, response.data);
      return robots.isAllowed(url, 'openVman-gateway') ?? true;
    } catch {
      return true; // if robots.txt unavailable, allow
    }
  }

  async healthCheck(): Promise<boolean> {
    return true;
  }
}
