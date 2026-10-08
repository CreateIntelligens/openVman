import pytest
from core.turn_decisions import TurnDecision, TurnPolicy
from protocol.protocol_events import validate_server_event, ProtocolValidationError

def test_debug_event_contract_only_allows_sanitized_diagnostics():
    payload = {'event': 'server_decision_debug', 'session_id': 'session', 'scope': 'text',
               'diagnostics': TurnDecision('turn', TurnPolicy(tone='confused'), 'clef').to_debug_payload()}
    validate_server_event(payload)
    payload['raw_user_text'] = 'should never leave the server'
    with pytest.raises(ProtocolValidationError):
        validate_server_event(payload)
