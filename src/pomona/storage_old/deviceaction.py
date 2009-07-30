#!/usr/bin/python

import copy

from devices import StorageDevice, PartitionDevice
from formats import getFormat
from errors import *
from udev import *

# The values are just hints as to the ordering.
# Eg: fsmod and devmod ordering depends on the mod (shrink -v- grow)
ACTION_TYPE_NONE = 0
ACTION_TYPE_DESTROY = 1000
ACTION_TYPE_RESIZE = 500
ACTION_TYPE_MIGRATE = 250
ACTION_TYPE_CREATE = 100

action_strings = {ACTION_TYPE_NONE: "None",
                  ACTION_TYPE_DESTROY: "Destroy",
                  ACTION_TYPE_RESIZE: "Resize",
                  ACTION_TYPE_MIGRATE: "Migrate",
                  ACTION_TYPE_CREATE: "Create"}

ACTION_OBJECT_NONE = 0
ACTION_OBJECT_FORMAT = 1
ACTION_OBJECT_DEVICE = 2

object_strings = {ACTION_OBJECT_NONE: "None",
                  ACTION_OBJECT_FORMAT: "Format",
                  ACTION_OBJECT_DEVICE: "Device"}

RESIZE_SHRINK = 88
RESIZE_GROW = 89

resize_strings = {RESIZE_SHRINK: "Shrink",
                  RESIZE_GROW: "Grow"}

def action_type_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in action_strings.items():
        if v.lower() == type_string.lower():
            return k

    return resize_type_from_string(type_string)

def action_object_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in object_strings.items():
        if v.lower() == type_string.lower():
            return k

def resize_type_from_string(type_string):
    if type_string is None:
        return None

    for (k,v) in resize_strings.items():
        if v.lower() == type_string.lower():
            return k

class DeviceAction(object):
    """ An action that will be carried out in the future on a Device.

        These classes represent actions to be performed on devices or
        filesystems.

        The operand Device instance will be modified according to the
        action, but no changes will be made to the underlying device or
        filesystem until the DeviceAction instance's execute method is
        called. The DeviceAction instance's cancel method should reverse
        any modifications made to the Device instance's attributes.

        If the Device instance represents a pre-existing device, the
        constructor should call any methods or set any attributes that the
        action will eventually change. Device/DeviceFormat classes should verify
        that the requested modifications are reasonable and raise an
        exception if not.

        Only one action of any given type/object pair can exist for any
        given device at any given time. This is enforced by the
        DeviceTree.

        Basic usage:

            a = DeviceAction(dev)
            a.execute()

            OR

            a = DeviceAction(dev)
            a.cancel()


        XXX should we back up the device with a deep copy for forcibly
            cancelling actions?

            The downside is that we lose any checking or verification that
            would get done when resetting the Device instance's attributes to
            their original values.

            The upside is that we would be guaranteed to achieve a total
            reversal. No chance of, eg: resizes ending up altering Device
            size due to rounding or other miscalculation.
"""
    type = ACTION_TYPE_NONE
    obj = ACTION_OBJECT_NONE

    def __init__(self, installer, device):
        self.installer = installer
        if not isinstance(device, StorageDevice):
            raise ValueError("arg 1 must be a StorageDevice instance")
        self.device = device


    def execute(self, intf=None):
        """ perform the action """
        pass

    def cancel(self):
        """ cancel the action """
        pass

    def isDestroy(self):
        return self.type == ACTION_TYPE_DESTROY

    def isCreate(self):
        return self.type == ACTION_TYPE_CREATE

    def isMigrate(self):
        return self.type == ACTION_TYPE_MIGRATE

    def isResize(self):
        return self.type == ACTION_TYPE_RESIZE

    def isShrink(self):
        return (self.type == ACTION_TYPE_RESIZE and self.dir == RESIZE_SHRINK)

    def isGrow(self):
        return (self.type == ACTION_TYPE_RESIZE and self.dir == RESIZE_GROW)

    def isDevice(self):
        return self.obj == ACTION_OBJECT_DEVICE

    def isFormat(self):
        return self.obj == ACTION_OBJECT_FORMAT

    def __str__(self):
        s = "%s %s" % (action_strings[self.type], object_strings[self.obj])
        if self.isResize():
            s += " (%s)" % resize_strings[self.dir]
        if self.isFormat():
            if self.device.format:
                fmt_type = self.device.format.type
            else:
                fmt_type = None
            s += " %s on" % fmt_type
        if self.isMigrate():
            pass
        s += " %s (%s)" % (self.device.name, self.device.type)
        return s

class ActionCreateDevice(DeviceAction):
    """ Action representing the creation of a new device. """
    type = ACTION_TYPE_CREATE
    obj = ACTION_OBJECT_DEVICE

    def __init__(self, installer, device):
        # FIXME: assert device.fs is None
        DeviceAction.__init__(self, installer, device)

    def execute(self, intf=None):
        self.device.create(intf=intf)


class ActionDestroyDevice(DeviceAction):
    """ An action representing the deletion of an existing device. """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_DEVICE

    def __init__(self, installer, device):
        # XXX should we insist that device.fs be None?
        DeviceAction.__init__(self, installer, device)
        if device.exists:
            device.teardown()

    def execute(self, intf=None):
        self.device.destroy()


class ActionResizeDevice(DeviceAction):
    """ An action representing the resizing of an existing device. """
    type = ACTION_TYPE_RESIZE
    obj = ACTION_OBJECT_DEVICE

    def __init__(self, installer, device, newsize):
        if device.currentSize == newsize:
            raise ValueError("new size same as old size")

        if not device.resizable:
            raise ValueError("device is not resizable")

        DeviceAction.__init__(self, installer, device)
        if newsize > device.currentSize:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK
        self.origsize = device.targetSize
        self.device.targetSize = newsize

    def execute(self, intf=None):
        self.device.resize(intf=intf)

    def cancel(self):
        self.device.targetSize = self.origsize


class ActionCreateFormat(DeviceAction):
    """ An action representing creation of a new filesystem. """
    type = ACTION_TYPE_CREATE
    obj = ACTION_OBJECT_FORMAT

    def __init__(self, installer, device, format=None):
        DeviceAction.__init__(self, installer, device)
        if format:
            self.origFormat = device.format
            if self.device.format.exists:
                self.device.format.teardown()
            self.device.format = format
        else:
            self.origFormat = getFormat(self.installer, None)

    def execute(self, intf=None):
        if isinstance(self.device, PartitionDevice):
            if self.format.partedFlag is not None:
                self.device.setFlag(self.format.partedFlag)
                self.device.disk.commit()

        udev_settle()
        self.device.setup()
        self.device.format.create(intf=intf,
                                  device=self.device.path,
                                  options=self.device.formatArgs)
        # Get the UUID now that the format is created
        udev_settle()
        self.device.updateSysfsPath()
        info = udev_get_block_device("/sys%s" % self.device.sysfsPath)
        self.device.format.uuid = udev_device_get_uuid(info)

    def cancel(self):
        self.device.format = self.origFormat

    @property
    def format(self):
        return self.device.format


class ActionDestroyFormat(DeviceAction):
    """ An action representing the removal of an existing filesystem.

        XXX this seems unnecessary
    """
    type = ACTION_TYPE_DESTROY
    obj = ACTION_OBJECT_FORMAT

    def __init__(self, installer, device):
        DeviceAction.__init__(self, installer, device)
        # Save a deep copy of the device stack this format occupies.
        # This is necessary since the stack of devices and formats
        # required to get to this format may get yanked out from under
        # us between now and execute.
        self._device = copy.deepcopy(device)
        self.origFormat = self._device.format
        if device.format.exists:
            device.format.teardown()
        self.device.format = None

    def execute(self, intf=None):
        """ wipe the filesystem signature from the device """
        if self.origFormat:
            if isinstance(self.device, PartitionDevice) and \
               self.origFormat.partedFlag is not None:
                # unset partition flags and commit
                self.device.unsetFlag(self.origFormat.partedFlag)
                self.device.disk.commit()
                udev_settle()

            # set up our copy of the original device stack since the
            # reference we got may have had any number of things changed
            # since then (most notably, formats removed by this very
            # class' constructor)
            self._device.setup()
            self.origFormat.destroy()
            udev_settle()
            self._device.teardown()

    def cancel(self):
        self.device.format = self.origFormat

    @property
    def format(self):
        return self.origFormat


class ActionResizeFormat(DeviceAction):
    """ An action representing the resizing of an existing filesystem.

        XXX Do we even want to support resizing of a filesystem without
            also resizing the device it resides on?
    """
    type = ACTION_TYPE_RESIZE
    obj = ACTION_OBJECT_FORMAT

    def __init__(self, installer, device, newsize):
        if device.targetSize == newsize:
            raise ValueError("new size same as old size")

        DeviceAction.__init__(self, installer, device)
        if newsize > device.format.currentSize:
            self.dir = RESIZE_GROW
        else:
            self.dir = RESIZE_SHRINK
        self.origSize = self.device.format.targetSize
        self.device.format.targetSize = newsize

    def execute(self, intf=None):
        self.device.setup()
        self.device.format.doResize(intf=intf)

    def cancel(self):
        self.device.format.targetSize = self.origSize

class ActionMigrateFormat(DeviceAction):
    """ An action representing the migration of an existing filesystem. """
    type = ACTION_TYPE_MIGRATE
    obj = ACTION_OBJECT_FORMAT

    def __init__(self, installer, device):
        if not device.format.migratable or not device.format.exists:
            raise ValueError("device format is not migratable")

        DeviceAction.__init__(self, installer, device)
        self.device.format.migrate = True

    def execute(self, intf=None):
        self.device.setup()
        self.device.format.doMigrate(intf=intf)

    def cancel(self):
        self.device.format.migrate = False
