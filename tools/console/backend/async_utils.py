"""遠隔処理の終了を確認するための非同期処理補助。"""

import asyncio
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass
class CancellationState:
    canceled: bool = False


async def await_shielded(task: asyncio.Task[T], state: CancellationState) -> T:
    """繰り返しの中断要求を記録し、内部タスクの終了まで待つ。"""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            state.canceled = True
