import unittest
from app.session_manager import SessionManager

class TestSessionManager(unittest.TestCase):
    def test_create_session(self):
        manager = SessionManager()
        session = manager.create_session("client_001")
        self.assertEqual(session.client_id, "client_001")
        self.assertIn(session.session_id, manager.active_sessions)

    def test_get_session(self):
        manager = SessionManager()
        session = manager.create_session("client_002")
        retrieved = manager.get_session(session.session_id)
        self.assertEqual(retrieved, session)

    def test_remove_session(self):
        manager = SessionManager()
        session = manager.create_session("client_003")
        manager.remove_session(session.session_id)
        self.assertIsNone(manager.get_session(session.session_id))

if __name__ == "__main__":
    unittest.main()
