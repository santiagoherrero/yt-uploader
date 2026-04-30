import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import pyudev

from .processor import Processor

log = logging.getLogger(__name__)


class DiskWatcher:
    def __init__(
        self,
        processor: Processor,
        settle_seconds: int,
        read_only: bool,
    ) -> None:
        self._processor = processor
        self._settle = settle_seconds
        self._read_only = read_only

    def run(self) -> None:
        ctx = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(ctx)
        monitor.filter_by(subsystem="block")
        monitor.start()

        log.info("Watching for new block devices (USB drives, pendrives)...")
        for device in iter(monitor.poll, None):
            if device.action != "add":
                continue
            if device.get("DEVTYPE") != "partition":
                continue
            if not device.get("ID_FS_TYPE"):
                continue
            if device.get("ID_BUS") not in ("usb", "ata", "scsi", None):
                continue
            try:
                self._handle(device)
            except Exception:
                log.exception("Error handling device %s", device.device_node)

    def _handle(self, device: pyudev.Device) -> None:
        dev_node = device.device_node
        fs_type = device.get("ID_FS_TYPE", "?")
        label = device.get("ID_FS_LABEL", "")
        uuid = device.get("ID_FS_UUID", "nouuid")
        log.info("New partition: %s (fs=%s label=%r uuid=%s)", dev_node, fs_type, label, uuid)

        time.sleep(self._settle)

        mount_point = self._existing_mount(dev_node)
        we_mounted: Optional[Path] = None
        if mount_point is None:
            mount_point = self._mount(dev_node, uuid, fs_type)
            we_mounted = mount_point

        if mount_point is None:
            log.warning("Could not access %s; skipping", dev_node)
            return

        try:
            self._processor.process_mount(mount_point)
        finally:
            if we_mounted is not None:
                self._unmount(we_mounted)

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

    def _unmount(self, mount_point: Path) -> None:
        try:
            subprocess.run(["umount", str(mount_point)], check=True, capture_output=True, text=True)
            log.info("Unmounted %s", mount_point)
        except subprocess.CalledProcessError as e:
            log.warning("umount %s failed: %s", mount_point, e.stderr.strip())
            return
        try:
            mount_point.rmdir()
        except OSError:
            pass
