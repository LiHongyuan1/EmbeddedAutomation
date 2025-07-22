# -*- coding: utf-8 -*-
"""
Generic & reusable ADB helper.

Author : lihongyuan
Date   : 2025-07-22
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# optional dependency：pure-python-adb (pip install pure-python-adb)
# 如果你的环境已安装官方 adb 并倾向于直接 shell 调用，也可以自行替换
# ---------------------------------------------------------------------------
try:
    from ppadb.client import Client as AdbClient
except ImportError as exc:  # 延迟提示，方便在无 ppadb 场景继续工作
    raise RuntimeError(
        "ppadb is required. Run `pip install pure-python-adb` first."
    ) from exc

_LOG = logging.getLogger("adb_helper")
if not _LOG.handlers:
    # 默认简单输出到 stdout，工程里可自行配置 logging.basicConfig
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _LOG.addHandler(_handler)
    _LOG.setLevel(logging.INFO)

# ---------------------------------------------------------------------------


class ADBError(RuntimeError):
    """顶层自定义异常，所有 adb 相关错误统一转为该类。"""


def _wrap_exc(func: Callable) -> Callable:
    """
    装饰器：把 ppadb / subprocess 抛出的异常转成 ADBError，避免外层混用多种异常。
    """

    def _inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise ADBError(str(exc)) from exc

    return _inner


@dataclass
class DeviceInfo:
    """部分常用属性，可按需扩展"""

    serial: str
    model: str = ""
    manufacturer: str = ""
    android_version: str = ""


class Device:
    """
    单台 Android 设备的轻量包装。
    外部不要直接持有 ppadb 的 device 对象，而使用该类统一接口。
    """

    def __init__(self, ppadb_device):
        self._d = ppadb_device  # 内部真实句柄

    # -------------------- 基础能力 --------------------

    @_wrap_exc
    def shell(self, cmd: str, timeout: int = 30) -> str:
        """执行 adb shell 命令并返回结果（去掉末尾换行）"""
        return self._d.shell(cmd, timeout=timeout).rstrip()

    @_wrap_exc
    def push(self, local: str | Path, remote: str) -> None:
        self._d.push(str(local), remote)

    @_wrap_exc
    def pull(self, remote: str, local: str | Path) -> None:
        self._d.pull(remote, str(local))

    @_wrap_exc
    def reboot(self, wait: bool = True, timeout: int = 180) -> None:
        """重启并（可选）等待设备重新上线"""
        _LOG.info("Reboot device %s ...", self.serial)
        self._d.reboot()
        if wait:
            self._wait_until_alive(timeout=timeout)

    @_wrap_exc
    def root(self) -> None:
        """切 root，如果已是 root 会直接返回"""
        if "uid=0" in self.shell("id"):
            return
        out = self._d.root()
        _LOG.info(out)

    @_wrap_exc
    def remount(self) -> None:
        """adb remount"""
        out = self._d.remount()
        _LOG.info(out)

    # -------------------- 属性 --------------------

    @property
    def serial(self) -> str:
        return self._d.serial

    @_wrap_exc
    def get_properties(self) -> Dict[str, str]:
        return self._d.get_properties()

    # 缓存常用字段，避免重复 adb 调用
    def get_info(self) -> DeviceInfo:
        props = self.get_properties()
        return DeviceInfo(
            serial=self.serial,
            manufacturer=props.get("ro.product.manufacturer", ""),
            model=props.get("ro.product.model", ""),
            android_version=props.get("ro.build.version.release", ""),
        )

    # -------------------- 私有工具 --------------------
    def _wait_until_alive(self, timeout: int = 180, interval: float = 2.0) -> None:
        start = time.time()
        while time.time() - start < timeout:
            try:
                self.shell("true", timeout=2)
                return
            except ADBError:
                time.sleep(interval)
        raise ADBError(f"device {self.serial} not ready after reboot")


class DeviceManager:
    """
    负责发现 / 管理多台设备
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 5037) -> None:
        self._client = AdbClient(host=host, port=port)
        self._refresh_devices()

    # -------------------- 设备枚举 --------------------
    @_wrap_exc
    def _refresh_devices(self) -> None:
        self._devices: Dict[str, Device] = {
            d.serial: Device(d) for d in self._client.devices()
        }

    def list_serials(self, refresh: bool = True) -> List[str]:
        if refresh:
            self._refresh_devices()
        return list(self._devices.keys())

    def get(self, serial: str) -> Device:
        """
        根据序列号返回 Device。
        注意：返回后如果设备掉线，需要重新 _refresh_devices。
        """
        if serial not in self._devices:
            self._refresh_devices()
        if serial not in self._devices:
            raise ADBError(f"device {serial} not found")
        return self._devices[serial]

    def pick_first(self) -> Device:
        """在仅连接一台设备的场景下使用；否则抛异常。"""
        self._refresh_devices()
        if len(self._devices) == 0:
            raise ADBError("no adb device online")
        if len(self._devices) > 1:
            raise ADBError(
                f"more than 1 device online: {', '.join(self._devices.keys())}"
            )
        return next(iter(self._devices.values()))

    # -------------------- 等待工具 --------------------
    def wait_for_devices(
        self,
        expect_num: int = 1,
        timeout: int = 120,
        interval: float = 2.0,
    ) -> List[str]:
        """
        阻塞直到 adb devices 至少出现 expect_num 台设备，返回序列号列表。
        """
        start = time.time()
        while time.time() - start < timeout:
            self._refresh_devices()
            if len(self._devices) >= expect_num:
                return list(self._devices.keys())
            _LOG.info(
                "waiting for %s device(s) online, current=%s ...",
                expect_num,
                len(self._devices),
            )
            time.sleep(interval)
        raise ADBError(
            f"only {len(self._devices)} device(s) online after {timeout} sec"
        )


# ---------------------------------------------------------------------------
# 下面示例展示如何在脚本中使用该库
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    mgr = DeviceManager()
    # 等待至少一台设备上线
    serials = mgr.wait_for_devices(1)
    first = mgr.get(serials[0])

    _LOG.info("connected device info: %s", first.get_info())

    # 例：root + remount
    first.root()
    first.remount()

    # 例：执行 shell
    uptime = first.shell("uptime -p")
    _LOG.info("device uptime: %s", uptime.strip())

    # 例：推拉文件
    local_tmp = Path(__file__).with_suffix(".tmp")
    local_tmp.write_text("hello adb\n", encoding="utf-8")
    first.push(local_tmp, "/sdcard/hello.txt")
    first.pull("/sdcard/hello.txt", local_tmp.with_name("hello_back.txt"))
    _LOG.info("file push/pull done (%s)", local_tmp)

    # 例：重启并等待上线
    # first.reboot()
