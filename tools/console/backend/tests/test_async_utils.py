"""中断が重なっても遠隔操作の終了を待つ契約を確認する。"""

import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from async_utils import CancellationState, await_shielded


class ShieldedWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_waits_and_remembers_request(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            return "finished"

        inner = asyncio.create_task(operation())
        state = CancellationState()
        waiter = asyncio.create_task(await_shielded(inner, state))
        await started.wait()
        waiter.cancel()
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        release.set()
        self.assertEqual(await waiter, "finished")
        self.assertTrue(state.canceled)

    async def test_exception_preserves_cancellation_state(self):
        release = asyncio.Event()

        async def operation():
            await release.wait()
            raise ValueError("架空の失敗")

        inner = asyncio.create_task(operation())
        state = CancellationState()
        waiter = asyncio.create_task(await_shielded(inner, state))
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.sleep(0)
        release.set()
        with self.assertRaises(ValueError):
            await waiter
        self.assertTrue(state.canceled)

    async def test_canceled_inner_task_does_not_loop(self):
        task = asyncio.create_task(asyncio.sleep(30))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await await_shielded(task, CancellationState())
