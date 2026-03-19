import assert from 'node:assert/strict';
import test from 'node:test';

import { parseBackendServerConfig } from './config';

test('parseBackendServerConfig returns defaults', () => {
  const config = parseBackendServerConfig({});

  assert.equal(config.BACKEND_SERVER_PORT, 8080);
  assert.equal(config.BACKEND_SERVER_HOST, '0.0.0.0');
  assert.equal(config.LOG_LEVEL, 'info');
  assert.equal(config.LOG_PRETTY, true);
});

test('parseBackendServerConfig parses provided values', () => {
  const config = parseBackendServerConfig({
    BACKEND_SERVER_PORT: '9090',
    BACKEND_SERVER_HOST: '127.0.0.1',
    LOG_LEVEL: 'debug',
    LOG_PRETTY: 'false',
  });

  assert.equal(config.BACKEND_SERVER_PORT, 9090);
  assert.equal(config.BACKEND_SERVER_HOST, '127.0.0.1');
  assert.equal(config.LOG_LEVEL, 'debug');
  assert.equal(config.LOG_PRETTY, false);
});

test('parseBackendServerConfig rejects invalid booleans', () => {
  assert.throws(
    () =>
      parseBackendServerConfig({
        LOG_PRETTY: 'sometimes',
      }),
    /LOG_PRETTY/
  );
});
