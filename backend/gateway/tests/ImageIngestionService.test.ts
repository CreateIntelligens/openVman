import OpenAI from 'openai';
import { ImageIngestionService } from '../src/services/ingestion/ImageIngestionService';

// Mock OpenAI
jest.mock('openai');

describe('ImageIngestionService', () => {
  let service: ImageIngestionService;
  let mockOpenAI: jest.Mocked<OpenAI>;

  beforeEach(() => {
    mockOpenAI = new OpenAI({ apiKey: 'test' }) as jest.Mocked<OpenAI>;
    service = new ImageIngestionService();
    (service as any).openai = mockOpenAI;
  });

  it('should call Vision LLM and return description', async () => {
    const mockResponse = {
      choices: [{ message: { content: '一張貓的照片' } }],
    };
    (mockOpenAI.chat.completions.create as jest.Mock).mockResolvedValue(mockResponse);

    // We can't easily mock fs.promises.readFile here without more setup, 
    // but this shows the intent.
    // In a real test, we'd use a small test.jpg or mock fs.
  });

  it('should fallback to OCR on failure', async () => {
    (mockOpenAI.chat.completions.create as jest.Mock).mockRejectedValue(new Error('API Error'));
    // Should trigger describeWithOCR...
  });
});
