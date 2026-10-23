import assert from "node:assert/strict";
import { test } from "node:test";

import { installSpeakerTap } from "../../public/experiments/avatar-motion/recording-audio.js";

test("warm-up and all later SDK utterances feed the same recording destination", () => {
  class Node {
    constructor(context) { this.context = context; this.connections = []; }
    connect(destination) { this.connections.push(destination); return destination; }
  }
  let created = 0;
  const destination = {}, stream = {};
  let started = false, stopped = false;
  const context = {
    destination,
    createMediaStreamDestination: () => { created += 1; return { stream }; },
    createConstantSource: () => Object.assign(new Node(context), {
      offset: { value: 1 }, start: () => { started = true; }, stop: () => { stopped = true; },
    }),
  };
  const original = Node.prototype.connect;
  const capture = installSpeakerTap(Node);
  try {
    const warmUp = new Node(context), speech = new Node(context), secondSpeech = new Node(context);
    assert.equal(warmUp.connect(destination), destination);
    speech.connect(destination);
    secondSpeech.connect(destination);
    assert.equal(created, 1);
    assert.equal(started, true);
    assert.equal(capture.getStream(), stream);
    for (const source of [warmUp, speech, secondSpeech]) {
      assert.equal(source.connections.length, 2);
      assert.equal(source.connections[0], destination);
      assert.equal(source.connections[1], warmUp.connections[1]);
    }
    const unrelated = new Node(context);
    unrelated.connect({});
    assert.equal(unrelated.connections.length, 1);
  } finally { capture.restore(); }
  assert.equal(stopped, true);
  assert.equal(Node.prototype.connect, original);
});
