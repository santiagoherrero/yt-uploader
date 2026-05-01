import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import pyudev

from .notifier import TelegramNotifier, esc
from .processor import Processor

log = logging.getLogger(__name__)

ALLOWED_BUSES = {"usb", "mmc"}


class DiskWatcher:
    def __init__(
        self,
        processor: Processor,
        telegram: TelegramNotifier,
        settle_seconds: int,
        read_only: bool,
    ) -> None:
        self._processor = processor
        self._tg = telegram
        self._settle = settle_seconds
        self._read_only = read_only

    def run(self) -> None:
        ctx = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(ctx)
        monitor.filter_by(subsystem="block")
        monitor.start()

        self._scan_existing(ctx)

        log.info("Watching for new block devices (USB drives, SD cards)...")
        for device in iter(monitor.poll, None):
            if device.action != "add":
                continue
            if not self._matches(device):
                continue
            try:
                self._handle(device, settle=True)
            except Exception:
                log.exception("Error handling device %s", device.device_node)

    def _scan_existing(self, ctx: pyudev.Context) -> None:
        log.info("Scanning currently-present USB/SD partitions...")
        found = 0
        for device in ctx.list_devices(subsystem="block", DEVTYPE="partition"):
            if not self._matches(device):
                continue
            found += 1
            try:
                self._handle(device, settle=False)
            except Exception:
                log.exception("Error handling existing device %s", device.device_node)
        log.info("Initial scan done (%d device(s) processed).", found)

    def _matches(self, device: pyudev.Device) -> bool:
        if device.get("DEVTYPE") != "partition":
            return False
        if not device.get("ID_FS_TYPE"):
            return False
        if device.get("ID_BUS") in ALLOWED_BUSES:
            return True
        if device.get("ID_USB_DRIVER") or device.get("ID_USB_TYPE"):
            return True
        return False

    def _handle(self, device: pyudev.Device, settle: bool) -> None:
        dev_node = device.device_node
        fs_type = device.get("ID_FS_TYPE", "?")
        label = device.get("ID_FS_LABEL", "")
        uuid = device.get("ID_FS_UUID", "nouuid")
        log.info(
            "Partition: %s (fs=%s label=%r uuid=%s bus=%s)",
            dev_node,
            fs_type,
            label,
            uuid,
            device.get("ID_BUS"),
        )

        if settle:
            time.sleep(self._settle)

        mount_point = self._existing_mount(dev_node)
        if mount_point is not None and str(mount_point) == "/":
            log.info("Skipping rootfs mount %s", dev_node)
            return

        we_mounted: Optional[Path] = None
        if mount_point is None:
            mount_point = self._mount(dev_node, uuid, fs_type)
            we_mounted = mount_point

        if mount_point is None:
            self._tg.send(
                f"⚠️ Disco detectado en <code>{esc(dev_node)}</code> "
                f"(fs={esc(fs_type)}, label={esc(label) or '—'}) "
                "pero no se pudo montar. Mirá los logs con "
                "<code>journalctl -u yt-uploader -n 50</code>."
            )
            return

        try:
            self._processor.process_mount(mount_point)
        finally:
            if we_mounted is not None:
                ok = self._unmount(we_mounted)
                if ok:
                    self._tg.send(
                        "🔌 Disco desmontado. Ya podés desenchufarlo."
                    )
                else:
                    self._tg.send(
                        "⚠️ No pude desmontar el disco automáticamente. "
                        "Esperá unos segundos y revisá los logs antes de desenchufar."
                    )

    def _existing_mount(self, dev_node: str) -> Optional[Path]:
        try:
            with open("/proc/mounts", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == dev_node:
                        return Path(parts[1])
        except OSError:
            log.exception("Could not read /proc/mounts")
        return None

    def _mount(self, dev_node: str, uuid: str, fs_type: str) -> Optional[Path]:
        target = Path(f"/mnt/yt-uploader-{uuid}")
        target.mkdir(parents=True, exist_ok=True)
        opts = ["ro"] if self._read_only else ["rw"]
        cmd = ["mount", "-t", fs_type, "-o", ",".join(opts), dev_node, str(target)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            log.info("Mounted %s at %s (%s)", dev_node, target, ",".join(opts))
            return target
        except subprocess.CalledProcessError as e:
            log.error("mount failed for %s: %s", dev_node, e.stderr.strip())
            try:
                target.rmdir()
            except OSError:
                pass
            return None

    def _unmount(self, mount_point: Path) -> bool:
        try:
            subprocess.run(["umount", str(mount_point)], check=True, capture_output=True, text=True)
            log.info("Unmounted %s", mount_point)
        except subprocess.CalledProcessError as e:
            log.warning("umount %s failed: %s", mount_point, e.stderr.strip())
            return False
        try:
            mount_point.rmdir()
        except OSError:
            pass
        return True
