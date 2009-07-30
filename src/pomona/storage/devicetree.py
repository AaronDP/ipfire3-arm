#!/usr/bin/python

import os

import formats

from devicelibs import lvm
from devices import *
from errors import *
from udev import *

class DeviceTree:
    def __init__(self, installer):
        self.installer = installer
        self.storage = self.installer.ds.storage
        
        self._devices = []
        self._actions = []

        self._ignoredDisks = []
        for disk in self.storage.ignoredDisks:
            self.addIgnoredDisk(disk)

    def addIgnoredDisk(self, disk):
        self._ignoredDisks.append(disk)
        lvm.lvm_cc_addFilterRejectRegexp(disk)

    def populate(self):
        """ Locate all storage devices. """
        # each iteration scans any devices that have appeared since the
        # previous iteration
        old_devices = []
        ignored_devices = []
        while True:
            devices = []
            new_devices = udev_get_block_devices()

            for new_device in new_devices:
                found = False
                for old_device in old_devices:
                    if old_device['name'] == new_device['name']:
                        found = True
                        break

                if not found:
                    devices.append(new_device)

            if len(devices) == 0:
                # nothing is changing -- we are finished building devices
                break

            old_devices = new_devices
            self.installer.log.info("Devices to scan: %s" % [d['name'] for d in devices])
            for dev in devices:
                self.addUdevDevice(dev)

        # After having the complete tree we make sure that the system
        # inconsistencies are ignored or resolved.
        #for leaf in self.leaves:
        #    self._handleInconsistencies(leaf)

        #self.teardownAll()
        try:
            os.unlink("/etc/mdadm.conf")
        except OSError:
            pass

    @property
    def devices(self):
        """ Dict with device path keys and Device values. """
        devices = {}

        for device in self._devices:
            if device.path in devices:
                raise DeviceTreeError("duplicate paths in device tree")

            devices[device.path] = device

        return devices

    @property
    def filesystems(self):
        """ List of filesystems. """
        #""" Dict with mountpoint keys and filesystem values. """
        filesystems = []
        for dev in self.leaves:
            if dev.format and getattr(dev.format, 'mountpoint', None):
                filesystems.append(dev.format)

        return filesystems

    @property
    def leaves(self):
        """ List of all devices upon which no other devices exist. """
        leaves = [d for d in self._devices if d.isleaf]
        return leaves

    def teardownAll(self):
        """ Run teardown methods on all devices. """
        for device in self.leaves:
            try:
                device.teardown(recursive=True)
            except (DeviceError, DeviceFormatError, LVMError) as e:
                self.installer.log.info("Teardown of %s failed: %s" % (device.name, e))

    def _addDevice(self, newdev):
        """ Add a device to the tree.

            Raise ValueError if the device's identifier is already
            in the list.
        """
        if newdev.path in [d.path for d in self._devices]:
            raise ValueError("device is already in tree")

        # make sure this device's parent devices are in the tree already
        for parent in newdev.parents:
            if parent not in self._devices:
                raise DeviceTreeError("parent device not in tree")

        self._devices.append(newdev)
        self.installer.log.info("Added %s (%s) to device tree" % (newdev.name, newdev.type))
        #self.installer.log.info("    Status: %s" % newdev.status)
        #self.installer.log.info("    Format: %s" % newdev.format.type)

    def _removeDevice(self, dev, force=None, moddisk=True):
        """ Remove a device from the tree.

            Only leaves may be removed.
        """
        if dev not in self._devices:
            raise ValueError("Device '%s' not in tree" % dev.name)

        if not dev.isleaf and not force:
            self.installer.log.debug("%s has %d kids" % (dev.name, dev.kids))
            raise ValueError("Cannot remove non-leaf device '%s'" % dev.name)

        # if this is a partition we need to remove it from the parted.Disk
        if moddisk and isinstance(dev, PartitionDevice) and \
                dev.disk is not None:
            # if this partition hasn't been allocated it could not have
            # a disk attribute
            if dev.partedPartition.type == parted.PARTITION_EXTENDED and \
                    len(dev.disk.partedDisk.getLogicalPartitions()) > 0:
                raise ValueError("Cannot remove extended partition %s.  "
                        "Logical partitions present." % dev.name)

            dev.disk.partedDisk.removePartition(dev.partedPartition)

        self._devices.remove(dev)
        self.installer.log.debug("Removed %s (%s) from device tree" % (dev.name,
                                                                       dev.type))

        for parent in dev.parents:
            # Will this cause issues with garbage collection?
            #   Do we care about garbage collection? At all?
            parent.removeChild()

    def isIgnored(self, info):
        """ Return True if info is a device we should ignore.

            Arguments:

                info -- a dict representing a udev db entry

            TODO:

                - filtering of SAN/FC devices
                - filtering by driver?

        """
        sysfs_path = udev_device_get_sysfs_path(info)
        name = udev_device_get_name(info)
        if not sysfs_path:
            return None

        if name in self._ignoredDisks:
            return True

        for ignored in self._ignoredDisks:
            if ignored == os.path.basename(os.path.dirname(sysfs_path)):
                # this is a partition on a disk in the ignore list
                return True

        # Ignore partitions found on the raw disks which are part of a
        # dmraidset
        for set in self.getDevicesByType("dm-raid array"):
            for disk in set.parents:
                if disk.name == os.path.basename(os.path.dirname(sysfs_path)):
                    return True

        # Ignore loop and ram devices, we normally already skip these in
        # udev.py: enumerate_block_devices(), but we can still end up trying
        # to add them to the tree when they are slaves of other devices, this
        # happens for example with the livecd
        if name.startswith("loop") or name.startswith("ram"):
            return True

        # FIXME: check for virtual devices whose slaves are on the ignore list

    def getDeviceByName(self, name):
        found = None
        for device in self._devices:
            if device.name == name:
                found = device
                break
        return found

    def getDevicesByType(self, device_type):
        # TODO: expand this to catch device format types
        return [d for d in self._devices if d.type == device_type]

    def getDevicesByInstance(self, device_class):
        return [d for d in self._devices if isinstance(d, device_class)]

    def registerAction(self, action):
        """ Register an action to be performed at a later time.

            Modifications to the Device instance are handled before we
            get here.
        """
        if (action.isDestroy() or action.isResize() or \
            (action.isCreate() and action.isFormat())) and \
           action.device not in self._devices:
            raise DeviceTreeError("device is not in the tree")
        elif (action.isCreate() and action.isDevice()):
            # this allows multiple create actions w/o destroy in between;
            # we will clean it up before processing actions
            #raise DeviceTreeError("device is already in the tree")
            if action.device in self._devices:
                self._removeDevice(action.device)
            for d in self._devices:
                if d.path == action.device.path:
                    self._removeDevice(d)

        if action.isCreate() and action.isDevice():
            self._addDevice(action.device)
        elif action.isDestroy() and action.isDevice():
            self._removeDevice(action.device)
        elif action.isCreate() and action.isFormat():
            if isinstance(action.device.format, formats.fs.FS) and \
               action.device.format.mountpoint in self.filesystems:
                raise DeviceTreeError("mountpoint already in use")

        self.installer.log.debug("Registered action: %s" % action)
        self._actions.append(action)

    def addUdevDevice(self, info):
        # FIXME: this should be broken up into more discrete chunks
        name = udev_device_get_name(info)
        uuid = udev_device_get_uuid(info)
        sysfs_path = udev_device_get_sysfs_path(info)

        if self.isIgnored(info):
            #self.installer.log.debug("Ignoring %s (%s)" % (name, sysfs_path))
            return

        #self.installer.log.debug("Scanning %s (%s)..." % (name, sysfs_path))
        device = self.getDeviceByName(name)

        #
        # The first step is to either look up or create the device
        #
        if udev_device_is_dm(info):
            pass
        #    # try to look up the device
        #    if device is None and uuid:
        #        # try to find the device by uuid
        #        device = self.getDeviceByUuid(uuid)
        #
        #    if device is None:
        #        device = self.addUdevDMDevice(info)
        #elif udev_device_is_md(info):
        #    if device is None and uuid:
        #        # try to find the device by uuid
        #        device = self.getDeviceByUuid(uuid)
        #
        #    if device is None:
        #        device = self.addUdevMDDevice(info)
        #elif udev_device_is_cdrom(info):
        #    if device is None:
        #        device = self.addUdevOpticalDevice(info)
        #elif udev_device_is_dmraid(info):
            # This is special handling to avoid the "unrecognized disklabel"
            # code since dmraid member disks won't have a disklabel. We
            # use a StorageDevice because DiskDevices need disklabels.
            # Quite lame, but it doesn't matter much since we won't use
            # the StorageDevice instances for anything.
        #    if device is None:
        #        device = StorageDevice(name,
        #                        major=udev_device_get_major(info),
        #                        minor=udev_device_get_minor(info),
        #                        sysfsPath=sysfs_path, exists=True)
        #        self._addDevice(device)
        elif udev_device_is_disk(info):
            if device is None:
                device = self.addUdevDiskDevice(info)
        elif udev_device_is_partition(info):
            if device is None:
                device = self.addUdevPartitionDevice(info)

        # now handle the device's formatting
        #self.handleUdevDeviceFormat(info, device)

    def addUdevDiskDevice(self, info):
        name = udev_device_get_name(info)
        uuid = udev_device_get_uuid(info)
        sysfs_path = udev_device_get_sysfs_path(info)
        device = None

        try:
            device = DiskDevice(self.installer, name,
                              major=udev_device_get_major(info),
                              minor=udev_device_get_minor(info),
                              sysfsPath=sysfs_path,
                              initlabel=False)
        except DeviceUserDeniedFormatError: #drive not initialized?
            self.addIgnoredDisk(name)
            return

        self._addDevice(device)
        return device

    def addUdevPartitionDevice(self, info):
        name = udev_device_get_name(info)
        uuid = udev_device_get_uuid(info)
        sysfs_path = udev_device_get_sysfs_path(info)
        device = None

        disk_name = os.path.basename(os.path.dirname(sysfs_path))
        disk = self.getDeviceByName(disk_name)

        if disk is None:
            # create a device instance for the disk
            path = os.path.dirname(os.path.realpath(sysfs_path))
            new_info = udev_get_block_device(path)
            if new_info:
                self.addUdevDevice(new_info)
                disk = self.getDeviceByName(disk_name)

            if disk is None:
                # if the current device is still not in
                # the tree, something has gone wrong
                self.installer.log.error("Failure scanning device %s" % disk_name)
                return

        try:
            device = PartitionDevice(self.installer, name, sysfsPath=sysfs_path,
                                     major=udev_device_get_major(info),
                                     minor=udev_device_get_minor(info),
                                     exists=True, parents=[disk])
        except DeviceError:
            # corner case sometime the kernel accepts a partition table
            # which gets rejected by parted, in this case we will
            # prompt to re-initialize the disk, so simply skip the
            # faulty partitions.
            return

        self._addDevice(device)
        return device

    def getDependentDevices(self, dep):
        """ Return a list of devices that depend on dep.

            The list includes both direct and indirect dependents.
        """
        dependents = []

        # special handling for extended partitions since the logical
        # partitions and their deps effectively depend on the extended
        logicals = []
        if isinstance(dep, PartitionDevice) and dep.partType and \
           dep.isExtended:
            # collect all of the logicals on the same disk
            for part in self.getDevicesByInstance(PartitionDevice):
                if part.partType and part.isLogical and part.disk == dep.disk:
                    logicals.append(part)
