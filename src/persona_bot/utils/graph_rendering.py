"""全グラフの日本語フォント設定とmatplotlib操作の直列化を共有する。"""

from __future__ import annotations

import io
from collections.abc import Callable
from functools import wraps
import threading
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from matplotlib import font_manager, rcParams

from persona_bot.config.constants import GRAPH_FONT_FAMILY

if TYPE_CHECKING:
    # 型検査のためだけに読む。実行時の import でmatplotlibの設定に副作用を増やさない。
    from matplotlib.figure import Figure

_PLOT_LOCK = threading.Lock()
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def graph_font_context() -> dict[str, list[str]]:
    """共通候補の順序を保ち、未導入フォントによる警告を避ける。"""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    families = [family for family in GRAPH_FONT_FAMILY
                if family in installed or f"font.{family}" in rcParams]
    # 日本語フォント未導入でも描画自体は継続する。字形の準備はREADMEの手順で行う。
    return {"font.family": families or ["sans-serif"]}


def serialized_plot(function: Callable[_Params, _Result]) -> Callable[_Params, _Result]:
    """描画関数を共通ロックの下で実行する。装飾した関数の引数と戻り値の型はそのまま保つ。"""
    @wraps(function)
    def render(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        # matplotlibの共有設定・Figure管理を、統計と利用量の間でも保護する。
        with _PLOT_LOCK:
            return function(*args, **kwargs)
    return render


def save_figure_to_buffer(figure: Figure, **savefig_options: Any) -> io.BytesIO:
    """PNGの所有権を呼出元へ渡し、失敗時のバッファとFigureを回収する。"""
    from matplotlib import pyplot as plt

    buffer = io.BytesIO()
    try:
        figure.savefig(buffer, format="png", **savefig_options)
        buffer.seek(0)
        return buffer
    except BaseException:
        buffer.close()
        raise
    finally:
        plt.close(figure)
