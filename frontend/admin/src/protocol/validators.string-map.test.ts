import { describe, expect, it } from 'vitest';

import { expectStringMap } from './validators/shared';

describe('expectStringMap', () => {
  it('keeps server keys as plain data without touching the prototype', () => {
    const payload = JSON.parse('{"__proto__": "x", "constructor": "y", "asr": "breeze"}');

    const result = expectStringMap(payload, '1.0', 'server_init_ack', 'capabilities');

    expect(Object.keys(result).sort()).toEqual(['__proto__', 'asr', 'constructor']);
    expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
    expect(({} as Record<string, unknown>).asr).toBeUndefined();
  });
});
