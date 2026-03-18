import axios from 'axios';
import * as fs from 'fs';
import * as path from 'path';
import * as FormData from 'form-data';
import { config } from '../../config';
import { logger } from '../../utils/logger';

export interface DocumentIngestionResult {
  type: 'document_content';
  content: string;
  page_count?: number;
}

export class DocumentIngestionService {
  async parse(filePath: string, traceId: string): Promise<DocumentIngestionResult> {
    try {
      return await this.parseWithMarkitdown(filePath, traceId);
    } catch (err) {
      logger.warn({ event: 'document_parse_fallback', traceId, err });
      return { type: 'document_content', content: '（文件解析失敗）' };
    }
  }

  private async parseWithMarkitdown(filePath: string, traceId: string): Promise<DocumentIngestionResult> {
    const form = new FormData();
    form.append('file', fs.createReadStream(filePath), {
      filename: path.basename(filePath),
    });

    const response = await axios.post<{ markdown: string; page_count?: number }>(
      `${config.MARKITDOWN_URL}/convert`,
      form,
      {
        headers: form.getHeaders(),
        timeout: config.MEDIA_PROCESSING_TIMEOUT_MS,
      }
    );

    const { markdown, page_count } = response.data;
    logger.info({ event: 'document_parsed', traceId, page_count });
    return { type: 'document_content', content: markdown, page_count };
  }
}
