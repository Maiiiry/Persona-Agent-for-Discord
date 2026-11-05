"""systemd ジョブの終了確認と共通の出力整形。"""

import asyncio
import time
from typing import Callable

import remote_commands as rc
from ssh_session import CommandStateUnknownError, SshError


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


async def wait_for_service_job(session, service: str, *, timeout: float, poll: float,
                               unknown_message: str, on_wait: Callable[[], None] | None = None,
                               unknown_on_cancel: bool = True) -> None:
    """ジョブ消滅まで待ち、終了不明なら後続の更新を停止する。"""
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SshError("systemd ジョブの終了確認が期限を超えました。")
            result = await session.run(rc.service_job_command(service), label="サービス操作の終了確認", timeout=remaining)
            if result.exit_status != 0:
                raise SshError("systemd ジョブの状態を取得できませんでした。")
            if rc.parse_service_job(result.stdout) == 0:
                return
            if on_wait is not None:
                on_wait()
            await asyncio.sleep(min(poll, max(0, deadline - time.monotonic())))
    except asyncio.CancelledError:
        if unknown_on_cancel:
            session.command_state_unknown = True
        raise
    except Exception as error:
        session.command_state_unknown = True
        raise CommandStateUnknownError(unknown_message) from error
