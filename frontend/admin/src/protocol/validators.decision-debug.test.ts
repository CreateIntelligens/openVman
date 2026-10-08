import { describe, expect, it } from "vitest";
import { validateClientEvent, validateServerEvent } from "./validators";

describe("decision debug protocol events", () => {
  it("accepts the Live debug toggle", () => {
    expect(validateClientEvent({ event: "set_decision_debug", enabled: true })).toEqual({
      event: "set_decision_debug", enabled: true,
    });
  });

  it("preserves optional Live turn correlation fields", () => {
    expect(validateClientEvent({ event: "user_speak", text: "hi", timestamp: 1, turn_id: "turn-1" }))
      .toMatchObject({ turn_id: "turn-1" });
    expect(validateServerEvent({
      event: "user_transcription", session_id: "session", text: "hi", decision_turn_id: "live-2",
    })).toMatchObject({ decision_turn_id: "live-2" });
    expect(() => validateClientEvent({ event: "user_speak", text: "hi", timestamp: 1, turn_id: " " }))
      .toThrow(/user_speak.*turn_id/);
    expect(() => validateServerEvent({ event: "user_transcription", session_id: "s", text: "hi", decision_turn_id: " " }))
      .toThrow(/user_transcription.*decision_turn_id/);
  });

  it("accepts and forwards correlated server diagnostics", () => {
    const diagnostics = {
      turn_id: "live:session:3", status: "available", provider: "clef",
      hop_id: "clef-primary", model: "clef-flash", elapsed_ms: 43,
      signals: [], policy: { tone: "frustrated" },
    };
    expect(validateServerEvent({
      event: "server_decision_debug", session_id: "session",
      client_turn_id: "client-turn-3", scope: "text", diagnostics,
    })).toEqual({
      event: "server_decision_debug", session_id: "session",
      client_turn_id: "client-turn-3", scope: "text", diagnostics,
    });
  });

  it("rejects extra event-level diagnostic payload fields", () => {
    expect(() => validateServerEvent({
      event: "server_decision_debug", session_id: "session", scope: "text",
      diagnostics: {}, raw_user_text: "private",
    })).toThrow(/raw_user_text/);
  });
});
