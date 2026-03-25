import unittest
import asyncio
from app.session_manager import SessionManager, Session
from app.guard_agent import GuardAgent

class TestInterruptSequence(unittest.TestCase):
    def test_guard_agent_classification(self):
        guard = GuardAgent()
        
        # Should stop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_test():
            self.assertEqual(await guard.classify("請問現在幾點？"), "STOP")
            self.assertEqual(await guard.classify("為什麼要這樣？"), "STOP")
            self.assertEqual(await guard.classify("等一下，我有個問題"), "STOP")
            self.assertEqual(await guard.classify("這是一段比較長的文字，應該被視為有意圖的輸入"), "STOP")
            
            # Should ignore
            self.assertEqual(await guard.classify("喔"), "IGNORE")
            self.assertEqual(await guard.classify("嗯"), "IGNORE")
            self.assertEqual(await guard.classify(""), "IGNORE")
            
        loop.run_until_complete(run_test())

    def test_session_task_interruption(self):
        manager = SessionManager()
        session = manager.create_session("test_client")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def mock_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # Task was cancelled correctly
                return "cancelled"
            return "finished"

        async def run_test():
            task = loop.create_task(mock_task())
            session.add_task(task)
            
            self.assertEqual(len(session.active_tasks), 1)
            
            cancelled_count = await session.interrupt_tasks()
            self.assertEqual(cancelled_count, 1)
            self.assertEqual(len(session.active_tasks), 0)
            
        loop.run_until_complete(run_test())

if __name__ == "__main__":
    unittest.main()
