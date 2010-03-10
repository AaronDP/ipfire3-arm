#!/usr/bin/python

from devicetree import DeviceTree

from deviceaction import *
from devicelibs import lvm
from devicelibs.lvm import safeLvmName
from devices import *
from formats import get_default_filesystem_type
from udev import *

from constants import *

import gettext
_ = lambda x: gettext.ldgettext("pomona", x)

def storageInitialize(installer):
    storage = installer.ds.storage

    storage.shutdown()

    if installer.dispatch.dir == DISPATCH_BACK:
        return

    # XXX I don't understand why I have to do this
    udev_trigger(subsystem="block")

    #XXX Determine our cdrom drive/usb key here and add it to protectedPartiotions
    storage.reset()

class Storage(object):
    def __init__(self, installer):
        self.installer = installer

        self.protectedDisks = []
        self.clearDisks = []
        self.ignoredDisks = []

        self.defaultFSType = get_default_filesystem_type()
        self.defaultBootFSType = get_default_filesystem_type(boot=True)

        self.doAutoPartition = False
        self.encryptedAutoPart = False
        #self.autoPartitionRequests = []
        self.autoPartitionRequests = [PartSpec(mountpoint="/", fstype=self.defaultFSType, size=1024, grow=True),
                                      PartSpec(mountpoint="/boot", fstype=self.defaultFSType, size=75, grow=False),]

        #self.devicetree = DeviceTree(self.installer)
        self.devicetree = None

        self._nextID = 0

    def shutdown(self):
        self.installer.log.debug("Shutting down storage...")

    def reset(self):
        """ Reset storage configuration to reflect actual system state.

            This should rescan from scratch but not clobber user-obtained
            information like passphrases
        """
        #for device in self.devices:
        #    if device.format.type == "luks" and device.format.exists:
        #        self.__luksDevs[device.format.uuid] = device.format._LUKS__passphrase

        self.installer.window = self.installer.intf.waitWindow(_("Finding Devices"),
                                    _("Finding storage devices..."))
        self.devicetree = DeviceTree(self.installer)
        self.devicetree.populate()
        self.fsset = FSSet(self.installer)
        self.installer.window.pop()

    def checkNoDisks(self):
        """Check that there are valid disk devices."""
        if not self.disks:
            self.installer.intf.messageWindow(_("No Drives Found"),
                               _("An error has occurred - no valid devices were "
                                 "found on which to create new file systems. "
                                 "Please check your hardware for the cause "
                                 "of this problem."))
            return True
        return False

    def sanityCheck(self):
        """ Run a series of tests to verify the storage configuration.

            This function is called at the end of partitioning so that
            we can make sure you don't have anything silly (like no /,
            a really small /, etc).  Returns (errors, warnings) where
            each is a list of strings.
        """
        checkSizes = [('/usr', 250), ('/tmp', 50), ('/var', 384),
                      ('/home', 100), ('/boot', 75)]
        warnings = []
        errors = []

        filesystems = self.fsset.mountpoints
        root = self.fsset.rootDevice
        swaps = self.fsset.swapDevices
        #try:
        #    boot = self.anaconda.platform.bootDevice()
        #except DeviceError:
        #    boot = None
        boot = None

        if not root:
            errors.append(_("You have not defined a root partition (/), "
                            "which is required for installation of %s "
                            "to continue.") % (PRODUCT_NAME,))

        if root and root.size < 250:
            warnings.append(_("Your root partition is less than 250 "
                              "megabytes which is usually too small to "
                              "install %s.") % (PRODUCT_NAME,))

        recommended_size = 1024
        if (root and root.size < recommended_size):
            errors.append(_("Your / partition is less than %s "
                            "megabytes which is lower than recommended "
                            "for a normal %s install.")
                          %(recommended_size, PRODUCT_NAME))

        # livecds have to have the rootfs type match up
        #if (root and
        #    self.installer.backend.rootFsType and
        #    root.format.type != self.installer.backend.rootFsType):
        #    errors.append(_("Your / partition does not match the "
        #                    "the live image you are installing from.  "
        #                    "It must be formatted as %s.")
        #                  % (self.anaconda.backend.rootFsType,))

        for (mount, size) in checkSizes:
            if mount in filesystems and filesystems[mount].size < size:
                warnings.append(_("Your %s partition is less than %s "
                                  "megabytes which is lower than recommended "
                                  "for a normal %s install.")
                                %(mount, size, PRODUCT_NAME))

        usb_disks = []
        firewire_disks = []
        #for disk in self.disks:
        #    if isys.driveUsesModule(disk.name, ["usb-storage", "ub"]):
        #        usb_disks.append(disk)
        #    elif isys.driveUsesModule(disk.name, ["sbp2", "firewire-sbp2"]):
        #        firewire_disks.append(disk)

        uses_usb = False
        uses_firewire = False
        for device in filesystems.values():
            for disk in usb_disks:
                if device.dependsOn(disk):
                    uses_usb = True
                    break

            for disk in firewire_disks:
                if device.dependsOn(disk):
                    uses_firewire = True
                    break

        if uses_usb:
            warnings.append(_("Installing on a USB device.  This may "
                              "or may not produce a working system."))
        if uses_firewire:
            warnings.append(_("Installing on a FireWire device.  This may "
                              "or may not produce a working system."))

        if not boot:
            errors.append(_("You have not created a boot partition."))

        if (boot and boot.type == "mdarray" and
            boot.level != 1):
            errors.append(_("Bootable partitions can only be on RAID1 "
                            "devices."))

        # can't have bootable partition on LV
        if boot and boot.type == "lvmlv":
            errors.append(_("Bootable partitions cannot be on a "
                            "logical volume."))

        # most arches can't have boot on RAID
        if boot and boot.type == "mdarray" and not self.anaconda.platform.supportsMdRaidBoot:
            errors.append(_("Bootable partitions cannot be on a RAID "
                            "device."))

        # Lots of filesystems types don't support /boot.
        if boot and not boot.format.bootable:
            errors.append(_("Bootable partitions cannot be on an %s "
                            "filesystem.") % boot.format.name)

        # vfat /boot is insane.
        if (boot and boot == root and boot.format.type == "vfat"):
            errors.append(_("Bootable partitions cannot be on an %s "
                            "filesystem.") % boot.format.type)

        if (boot and filter(lambda d: d.type == "luks/dm-crypt",
                            self.deviceDeps(boot))):
            errors.append(_("Bootable partitions cannot be on an "
                            "encrypted block device"))

        if not swaps:
            warnings.append(_("You have not specified a swap partition.  "
                              "Although not strictly required in all cases, "
                              "it will significantly improve performance for "
                              "most installations."))

        return (errors, warnings)

    def deviceDeps(self, device):
        return self.devicetree.getDependentDevices(device)

    @property
    def nextID(self):
        id = self._nextID
        self._nextID += 1
        return id

    @property
    def disks(self):
        """ A list of the disks in the device tree.

            Ignored disks are not included, as are disks with no media present.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        disks = []
        devices = self.devicetree.devices
        for d in devices:
            if isinstance(devices[d], DiskDevice) and devices[d].mediaPresent:
                disks.append(devices[d])
        disks.sort(key=lambda d: d.name)
        return disks

    @property
    def devices(self):
        """ A list of all the devices in the device tree. """
        devices = self.devicetree.devices.values()
        devices.sort(key=lambda d: d.path)
        return devices

    @property
    def partitions(self):
        """ A list of the partitions in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        partitions = self.devicetree.getDevicesByInstance(PartitionDevice)
        partitions.sort(key=lambda d: d.name)
        return partitions

    @property
    def vgs(self):
        """ A list of the LVM Volume Groups in the device tree.

            This is based on the current state of the device tree and
            does not necessarily reflect the actual on-disk state of the
            system's disks.
        """
        vgs = self.devicetree.getDevicesByType("lvmvg")
        vgs.sort(key=lambda d: d.name)
        return vgs

    def createDevice(self, device):
        """ Schedule creation of a device.

            TODO: We could do some things here like assign the next
                  available raid minor if one isn't already set.
        """
        self.devicetree.registerAction(ActionCreateDevice(self.installer, device))
        if device.format.type:
            self.devicetree.registerAction(ActionCreateFormat(self.installer, device))

    def destroyDevice(self, device):
        """ Schedule destruction of a device. """
        if device.format.exists and device.format.type:
            # schedule destruction of any formatting while we're at it
            self.devicetree.registerAction(ActionDestroyFormat(self.installer, device))

        action = ActionDestroyDevice(self.installer, device)
        self.devicetree.registerAction(action)

    def newPartition(self, *args, **kwargs):
        """ Return a new PartitionDevice instance for configuring. """
        if kwargs.has_key("fmt_type"):
            kwargs["format"] = getFormat(kwargs.pop("fmt_type"), installer=self.installer,
                                         mountpoint=kwargs.pop("mountpoint", None))

        if kwargs.has_key("disks"):
            parents = kwargs.pop("disks")
            if isinstance(parents, Device):
                kwargs["parents"] = [parents]
            else:
                kwargs["parents"] = parents

        if kwargs.has_key("name"):
            name = kwargs.pop("name")
        else:
            name = "req%d" % self.nextID

        return PartitionDevice(self.installer, name, *args, **kwargs)

    def newVG(self, *args, **kwargs):
        """ Return a new LVMVolumeGroupDevice instance. """
        pvs = kwargs.pop("pvs", [])
        for pv in pvs:
            if pv not in self.devices:
                raise ValueError("pv is not in the device tree")

        if kwargs.has_key("name"):
            name = kwargs.pop("name")
        else:
            # XXX name = self.createSuggestedVGName(self.anaconda.id.network)
            name = self.createSuggestedVGName(None)

        if name in [d.name for d in self.devices]:
            raise ValueError("name already in use")

        return LVMVolumeGroupDevice(self.installer, name, pvs, *args, **kwargs)

    def newLV(self, *args, **kwargs):
        """ Return a new LVMLogicalVolumeDevice instance. """
        if kwargs.has_key("vg"):
            vg = kwargs.pop("vg")

        mountpoint = kwargs.pop("mountpoint", None)
        if kwargs.has_key("fmt_type"):
            kwargs["format"] = getFormat(kwargs.pop("fmt_type"),
                                         installer=self.installer,
                                         mountpoint=mountpoint)

        if kwargs.has_key("name"):
            name = kwargs.pop("name")
        else:
            if kwargs.get("format") and kwargs["format"].type == "swap":
                swap = True
            else:
                swap = False
            name = self.createSuggestedLVName(vg,
                                              swap=swap,
                                              mountpoint=mountpoint)

        if name in [d.name for d in self.devices]:
            raise ValueError("Name already in use")

        return LVMLogicalVolumeDevice(self.installer, name, vg, *args, **kwargs)

    def createSuggestedVGName(self, network):
        """ Return a reasonable, unused VG name. """
        # try to create a volume group name incorporating the hostname
        #hn = network.hostname # XXX
        hn = "%s.localdomain" % PROCUCT_SNAME
        vgnames = [vg.name for vg in self.vgs]
        if hn is not None and hn != '':
            if hn == 'localhost' or hn == 'localhost.localdomain':
                vgtemplate = "VolGroup"
            elif hn.find('.') != -1:
                hn = safeLvmName(hn)
                vgtemplate = "vg_%s" % (hn.split('.')[0].lower(),)
            else:
                hn = safeLvmName(hn)
                vgtemplate = "vg_%s" % (hn.lower(),)
        else:
            vgtemplate = "VolGroup"

        if vgtemplate not in vgnames and \
                vgtemplate not in lvm.lvm_vg_blacklist:
            return vgtemplate
        else:
            i = 0
            while 1:
                tmpname = "%s%02d" % (vgtemplate, i,)
                if not tmpname in vgnames and \
                        tmpname not in lvm.lvm_vg_blacklist:
                    break

                i += 1
                if i > 99:
                    tmpname = ""

            return tmpname

    def createSuggestedLVName(self, vg, swap=None, mountpoint=None):
        """ Return a suitable, unused name for a new logical volume. """
        # FIXME: this is not at all guaranteed to work
        if mountpoint:
            # try to incorporate the mountpoint into the name
            if mountpoint == '/':
                lvtemplate = 'lv_root'
            else:
                tmp = safeLvmName(mountpoint)
                lvtemplate = "lv_%s" % (tmp,)
        else:
            if swap:
                if len([s for s in self.swaps if s in vg.lvs]):
                    idx = len([s for s in self.swaps if s in vg.lvs])
                    while True:
                        lvtemplate = "lv_swap%02d" % idx
                        if lvtemplate in [lv.lvname for lv in vg.lvs]:
                            idx += 1
                        else:
                            break
                else:
                    lvtemplate = "lv_swap"
            else:
                idx = len(vg.lvs)
                while True:
                    lvtemplate = "LogVol%02d" % idx
                    if lvtemplate in [l.lvname for l in vg.lvs]:
                        idx += 1
                    else:
                        break

        return lvtemplate

    def deviceImmutable(self, device):
        """ Return any reason the device cannot be modified/removed.

            Return False if the device can be removed.

            Devices that cannot be removed include:

                - protected partitions
                - devices that are part of an md array or lvm vg
                - extended partition containing logical partitions that
                  meet any of the above criteria

        """
        if not isinstance(device, Device):
            raise ValueError("arg1 (%s) must be a Device instance" % device)

        if device.name in self.protectedDisks:
            return _("This partition is holding the data for the hard "
                      "drive install.")
        elif device.format.type == "mdmember":
            for array in self.mdarrays:
                if array.dependsOn(device):
                    if array.minor is not None:
                        return _("This device is part of the RAID "
                                 "device %s.") % (array.path,)
                    else:
                        return _("This device is part of a RAID device.")
        elif device.format.type == "lvmpv":
            for vg in self.vgs:
                if vg.dependsOn(device):
                    if vg.name is not None:
                        return _("This device is part of the LVM "
                                 "volume group '%s'.") % (vg.name,)
                    else:
                        return _("This device is part of a LVM volume "
                                 "group.")
        elif device.format.type == "luks":
            try:
                luksdev = self.devicetree.getChildren(device)[0]
            except IndexError:
                pass
            else:
                return self.deviceImmutable(luksdev)
        elif isinstance(device, PartitionDevice) and device.isExtended:
            reasons = {}
            for dep in self.deviceDeps(device):
                reason = self.deviceImmutable(dep)
                if reason:
                    reasons[dep.path] = reason
            if reasons:
                msg =  _("This device is an extended partition which "
                         "contains logical partitions that cannot be "
                         "deleted:\n\n")
                for dev in reasons:
                    msg += "%s: %s" % (dev, reasons[dev])
                return msg

        for i in self.devicetree.immutableDevices:
            if i[0] == device.name:
                return i[1]

        return False


class FSSet(object):
    """ A class to represent a set of filesystems. """
    def __init__(self, installer):
        self.installer = installer
        self.devicetree = installer.ds.storage.devicetree
        self.cryptTab = None
        self.blkidTab = None
        self.origFStab = None
        self.active = False
        self._dev = None
        self._devpts = None
        self._sysfs = None
        self._proc = None
        self._devshm = None

    @property
    def sysfs(self):
        if not self._sysfs:
            self._sysfs = NoDevice(format=getFormat("sysfs",
                                                    device="sys",
                                                    mountpoint="/sys"))
        return self._sysfs

    @property
    def dev(self):
        if not self._dev:
            self._dev = DirectoryDevice("/dev", format=getFormat("bind",
                                                                 device="/dev",
                                                                 mountpoint="/dev",
                                                                 exists=True),
                                        exists=True)

        return self._dev

    @property
    def devpts(self):
        if not self._devpts:
            self._devpts = NoDevice(format=getFormat("devpts",
                                                     device="devpts",
                                                     mountpoint="/dev/pts"))
        return self._devpts

    @property
    def proc(self):
        if not self._proc:
            self._proc = NoDevice(format=getFormat("proc",
                                                   device="proc",
                                                   mountpoint="/proc"))
        return self._proc

    @property
    def devshm(self):
        if not self._devshm:
            self._devshm = NoDevice(format=getFormat("tmpfs",
                                                     device="tmpfs",
                                                     mountpoint="/dev/shm"))
        return self._devshm

    @property
    def devices(self):
        devices = self.devicetree.devices.values()
        devices.sort(key=lambda d: d.path)
        return devices

    @property
    def mountpoints(self):
        filesystems = {}
        for device in self.devices:
            if device.format.mountable and device.format.mountpoint:
                filesystems[device.format.mountpoint] = device
        return filesystems

    def _parseOneLine(self, (devspec, mountpoint, fstype, options, dump, passno)):
        # find device in the tree
        device = self.devicetree.resolveDevice(devspec,
                                               cryptTab=self.cryptTab,
                                               blkidTab=self.blkidTab)
        if device:
            # fall through to the bottom of this block
            pass
        elif devspec.startswith("/dev/loop"):
            # FIXME: create devices.LoopDevice
            self.installer.log.warning("completely ignoring your loop mount")
        elif ":" in devspec:
            # NFS -- preserve but otherwise ignore
            device = NFSDevice(devspec,
                               format=getFormat(fstype,
                                                device=devspec))
        elif devspec.startswith("/") and fstype == "swap":
            # swap file
            device = FileDevice(devspec,
                                parents=get_containing_device(devspec, self.devicetree),
                                format=getFormat(fstype,
                                                 device=devspec,
                                                 exists=True),
                                exists=True)
        elif fstype == "bind" or "bind" in options:
            # bind mount... set fstype so later comparison won't
            # turn up false positives
            fstype = "bind"
            device = FileDevice(devspec,
                                parents=get_containing_device(devspec, self.devicetree),
                                exists=True)
            device.format = getFormat("bind",
                                      device=device.path,
                                      exists=True)
        elif mountpoint in ("/proc", "/sys", "/dev/shm", "/dev/pts"):
            # drop these now -- we'll recreate later
            return None
        else:
            # nodev filesystem -- preserve or drop completely?
            format = getFormat(fstype)
            if devspec == "none" or \
               isinstance(format, get_device_format_class("nodev")):
                device = NoDevice(format)
            else:
                device = StorageDevice(devspec)

        if device is None:
            self.installer.log.error("failed to resolve %s (%s) from fstab" % (devspec,
                                                                               fstype))
            return None

        # make sure, if we're using a device from the tree, that
        # the device's format we found matches what's in the fstab
        fmt = getFormat(fstype, device=device.path)
        if fmt.type != device.format.type:
            self.installer.log.warning("scanned format (%s) differs from fstab "
                                       "format (%s)" % (device.format.type, fstype))

        if device.format.mountable:
            device.format.mountpoint = mountpoint
            device.format.mountopts = options

        # is this useful?
        try:
            device.format.options = options
        except AttributeError:
            pass

        return device

    def parseFSTab(self, chroot=""):
        """ parse /etc/fstab

            preconditions:
                all storage devices have been scanned, including filesystems
            postconditions:

            FIXME: control which exceptions we raise

            XXX do we care about bind mounts?
                how about nodev mounts?
                loop mounts?
        """
        if not chroot or not os.path.isdir(chroot):
            chroot = ""

        path = "%s/etc/fstab" % chroot
        if not os.access(path, os.R_OK):
            # XXX should we raise an exception instead?
            self.installer.log.info("cannot open %s for read" % path)
            return

        blkidTab = BlkidTab(self.installer, chroot=chroot)
        try:
            blkidTab.parse()
            self.installer.log.debug("blkid.tab devs: %s" % blkidTab.devices.keys())
        except Exception as e:
            self.installer.log.info("error parsing blkid.tab: %s" % e)
            blkidTab = None

        cryptTab = CryptTab(self.devicetree, blkidTab=blkidTab, chroot=chroot)
        try:
            cryptTab.parse(chroot=chroot)
            self.installer.log.debug("crypttab maps: %s" % cryptTab.mappings.keys())
        except Exception as e:
            self.installer.log.info("error parsing crypttab: %s" % e)
            cryptTab = None

        self.blkidTab = blkidTab
        self.cryptTab = cryptTab

        with open(path) as f:
            self.installer.log.debug("parsing %s" % path)

            lines = f.readlines()

            # save the original file
            self.origFStab = ''.join(lines)

            for line in lines:
                # strip off comments
                (line, pound, comment) = line.partition("#")
                fields = line.split()

                if not 4 <= len(fields) <= 6:
                    continue
                elif len(fields) == 4:
                    fields.extend([0, 0])
                elif len(fields) == 5:
                    fields.append(0)

                (devspec, mountpoint, fstype, options, dump, passno) = fields

                try:
                    device = self._parseOneLine((devspec, mountpoint, fstype, options, dump, passno))
                except Exception as e:
                    raise Exception("fstab entry %s is malformed: %s" % (devspec, e))

                if not device:
                    continue

                if device not in self.devicetree.devices.values():
                    self.devicetree._addDevice(device)

    def fsFreeSpace(self, chroot='/'):
        space = []
        for device in self.devices:
            if not device.format.mountable or \
               not device.format.status:
                continue

            path = "%s/%s" % (chroot, device.format.mountpoint)
            try:
                space.append((device.format.mountpoint,
                              isys.pathSpaceAvailable(path)))
            except SystemError:
                self.installer.log.error("failed to calculate free space for %s" % (device.format.mountpoint,))

        space.sort(key=lambda s: s[1])
        return space

    def mtab(self):
        format = "%s %s %s %s 0 0\n"
        mtab = ""
        devices = self.mountpoints.values() + self.swapDevices
        devices.extend([self.devshm, self.devpts, self.sysfs, self.proc])
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", None))
        for device in devices:
            if not device.format.status:
                continue
            if not device.format.mountable:
                continue
            if device.format.mountpoint:
                options = device.format.mountopts
                if options:
                    options = options.replace("defaults,", "")
                    options = options.replace("defaults", "")

                if options:
                    options = "rw," + options
                else:
                    options = "rw"
                mtab = mtab + format % (device.path,
                                        device.format.mountpoint,
                                        device.format.type,
                                        options)
        return mtab

    def turnOnSwap(self):
        intf = self.installer.intf
        for device in self.swapDevices:
            try:
                device.setup()
                device.format.setup()
            except SuspendError:
                if intf:
                    msg = _("The swap device:\n\n     %s\n\n"
                            "in your /etc/fstab file is currently in "
                            "use as a software suspend device, "
                            "which means your system is hibernating. "
                            "If you are performing a new install, "
                            "make sure the installer is set "
                            "to format all swap devices.") \
                            % device.path
                    intf.messageWindow(_("Error"), msg)
                sys.exit(0)
            except DeviceError as msg:
                if intf:
                    err = _("Error enabling swap device %s: %s\n\n"
                            "This most likely means this swap "
                            "device has not been initialized.\n\n"
                            "Press OK to exit the installer.") % \
                            (device.path, msg)
                    intf.messageWindow(_("Error"), err)
                sys.exit(0)

    def mountFilesystems(self, installer, raiseErrors=None, readOnly=None,
                         skipRoot=False):
        intf = installer.intf
        devices = self.mountpoints.values() + self.swapDevices
        devices.extend([self.dev, self.devshm, self.devpts, self.sysfs, self.proc])
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", None))

        for device in devices:
            if not device.format.mountable or not device.format.mountpoint:
                continue

            if skipRoot and device.format.mountpoint == "/":
                continue

            options = device.format.options
            if "noauto" in options.split(","):
                continue

            try:
                device.setup()
            except Exception as msg:
                # FIXME: need an error popup
                continue

            if readOnly:
                options = "%s,%s" % (options, readOnly)

            try:
                device.format.setup(options=options,
                                    chroot=installer.rootPath)
            except OSError as (num, msg):
                if intf:
                    if num == errno.EEXIST:
                        intf.messageWindow(_("Invalid mount point"),
                                           _("An error occurred when trying "
                                             "to create %s.  Some element of "
                                             "this path is not a directory. "
                                             "This is a fatal error and the "
                                             "install cannot continue.\n\n"
                                             "Press <Enter> to exit the "
                                             "installer.")
                                           % (device.format.mountpoint,))
                    else:
                        intf.messageWindow(_("Invalid mount point"),
                                           _("An error occurred when trying "
                                             "to create %s: %s.  This is "
                                             "a fatal error and the install "
                                             "cannot continue.\n\n"
                                             "Press <Enter> to exit the "
                                             "installer.")
                                            % (device.format.mountpoint, msg))
                self.installer.log.error("OSError: (%d) %s" % (num, msg) )
                sys.exit(0)
            except SystemError as (num, msg):
                if raiseErrors:
                    raise
                if intf and not device.format.linuxNative:
                    ret = intf.messageWindow(_("Unable to mount filesystem"),
                                             _("An error occurred mounting "
                                             "device %s as %s.  You may "
                                             "continue installation, but "
                                             "there may be problems.") %
                                             (device.path,
                                              device.format.mountpoint),
                                             type="custom",
                                             custom_icon="warning",
                                             custom_buttons=[_("_Exit installer"),
                                                            _("_Continue")])

                    if ret == 0:
                        sys.exit(0)
                    else:
                        continue

                self.installer.log.error("SystemError: (%d) %s" % (num, msg) )
                sys.exit(0)
            except FSError as msg:
                if intf:
                    intf.messageWindow(_("Unable to mount filesystem"),
                                       _("An error occurred mounting "
                                         "device %s as %s: %s. This is "
                                         "a fatal error and the install "
                                         "cannot continue.\n\n"
                                         "Press <Enter> to exit the "
                                         "installer.")
                                        % (device.path,
                                           device.format.mountpoint,
                                           msg))
                self.installer.log.error("FSError: %s" % msg)
                sys.exit(0)

        self.active = True

    def umountFilesystems(self, instPath, ignoreErrors=True, swapoff=True):
        devices = self.mountpoints.values() + self.swapDevices
        devices.extend([self.dev, self.devshm, self.devpts, self.sysfs, self.proc])
        devices.sort(key=lambda d: getattr(d.format, "mountpoint", None))
        devices.reverse()
        for device in devices:
            if not device.format.mountable and \
               (device.format.type != "swap" or swapoff):
                continue

            device.format.teardown()
            device.teardown()

        self.active = False

    def createSwapFile(self, rootPath, device, size):
        """ Create and activate a swap file under rootPath. """
        filename = "/SWAP"
        count = 0
        basedir = os.path.normpath("%s/%s" % (rootPath,
                                              device.format.mountpoint))
        while os.path.exists("%s/%s" % (basedir, filename)) or \
              self.devicetree.getDeviceByName(filename):
            file = os.path.normpath("%s/%s" % (basedir, filename))
            count += 1
            filename = "/SWAP-%d" % count

        dev = FileDevice(filename,
                         size=size,
                         parents=[device],
                         format=getFormat("swap", device=filename))
        dev.create()
        dev.setup()
        dev.format.create()
        dev.format.setup()
        # nasty, nasty
        self.devicetree._addDevice(dev)

    def mkDevRoot(self, instPath):
        root = self.rootDevice
        dev = "%s/%s" % (instPath, root.path)
        if not os.path.exists("%s/dev/root" %(instPath,)) and os.path.exists(dev):
            rdev = os.stat(dev).st_rdev
            os.mknod("%s/dev/root" % (instPath,), stat.S_IFBLK | 0600, rdev)

    @property
    def swapDevices(self):
        swaps = []
        for device in self.devices:
            if device.format.type == "swap":
                swaps.append(device)
        return swaps

    @property
    def rootDevice(self):
        for device in self.devices:
            try:
                mountpoint = device.format.mountpoint
            except AttributeError:
                mountpoint = None

            if mountpoint == "/":
                return device

    @property
    def migratableDevices(self):
        """ List of devices whose filesystems can be migrated. """
        migratable = []
        for device in self.devices:
            if device.format.migratable and device.format.exists:
                migratable.append(device)

        return migratable

    def write(self, instPath):
        """ write out all config files based on the set of filesystems """
        # /etc/fstab
        fstab_path = os.path.normpath("%s/etc/fstab" % instPath)
        fstab = self.fstab()
        open(fstab_path, "w").write(fstab)

        # /etc/crypttab
        crypttab_path = os.path.normpath("%s/etc/crypttab" % instPath)
        crypttab = self.crypttab()
        open(crypttab_path, "w").write(crypttab)

        # /etc/mdadm.conf
        mdadm_path = os.path.normpath("%s/etc/mdadm.conf" % instPath)
        mdadm_conf = self.mdadmConf()
        open(mdadm_path, "w").write(mdadm_conf)

    def crypttab(self):
        # if we are upgrading, do we want to update crypttab?
        # gut reaction says no, but plymouth needs the names to be very
        # specific for passphrase prompting
        if not self.cryptTab:
            self.cryptTab = CryptTab(self.devicetree)
            self.cryptTab.populate()

        devices = self.mountpoints.values() + self.swapDevices

        # prune crypttab -- only mappings required by one or more entries
        for name in self.cryptTab.mappings.keys():
            keep = False
            mapInfo = self.cryptTab[name]
            cryptoDev = mapInfo['device']
            for device in devices:
                if device == cryptoDev or device.dependsOn(cryptoDev):
                    keep = True
                    break

            if not keep:
                del self.cryptTab.mappings[name]

        return self.cryptTab.crypttab()

    def mdadmConf(self):
        """ Return the contents of mdadm.conf. """
        arrays = self.devicetree.getDevicesByType("mdarray")
        conf = ""
        devices = self.mountpoints.values() + self.swapDevices
        for array in arrays:
            writeConf = False
            for device in devices:
                if device == array or device.dependsOn(array):
                    writeConf = True
                    break

            if writeConf:
                conf += array.mdadmConfEntry

        return conf

    def fstab (self):
        format = "%-23s %-23s %-7s %-15s %d %d\n"
        fstab = """
#
# /etc/fstab
# Created by pomona on %s
#
# Accessible filesystems, by reference, are maintained under '/dev/disk'
# See man pages fstab(5), findfs(8), mount(8) and/or vol_id(8) for more info
#
""" % time.asctime()

        devices = self.mountpoints.values() + self.swapDevices
        devices.extend([self.devshm, self.devpts, self.sysfs, self.proc])
        netdevs = self.devicetree.getDevicesByInstance(NetworkStorageDevice)
        for device in devices:
            # why the hell do we put swap in the fstab, anyway?
            if not device.format.mountable and device.format.type != "swap":
                continue

            fstype = device.format.type
            if fstype == "swap":
                mountpoint = "swap"
                options = device.format.options
            else:
                mountpoint = device.format.mountpoint
                options = device.format.mountopts
                if not mountpoint:
                    self.installer.log.warning("%s filesystem on %s has no mountpoint" % \
                                               (fstype, device.path))
                    continue

            options = options or "defaults"
            for netdev in netdevs:
                if device.dependsOn(netdev):
                    options = options + ",_netdev"
                    break
            devspec = device.fstabSpec
            dump = device.format.dump
            if device.format.check and mountpoint == "/":
                passno = 1
            elif device.format.check:
                passno = 2
            else:
                passno = 0
            fstab = fstab + device.fstabComment
            fstab = fstab + format % (devspec, mountpoint, fstype,
                                      options, dump, passno)
        return fstab

class PartSpec(object):
    def __init__(self, mountpoint=None, fstype=None, size=None, maxSize=None,
                 grow=False, asVol=False, weight=0):
        self.mountpoint = mountpoint
        self.fstype = fstype
        self.size = size
        self.maxSize = maxSize
        self.grow = grow
        self.asVol = asVol
        self.weight = weight


class BlkidTab(object):
    """ Dictionary-like interface to blkid.tab with device path keys """
    def __init__(self, installer, chroot=""):
        self.installer = installer
        self.chroot = chroot
        self.devices = {}

    def parse(self):
        path = "%s/etc/blkid/blkid.tab" % self.chroot
        self.installer.log.debug("parsing %s" % path)
        with open(path) as f:
            for line in f.readlines():
                # this is pretty ugly, but an XML parser is more work than
                # is justifiable for this purpose
                if not line.startswith("<device "):
                    continue

                line = line[len("<device "):-len("</device>\n")]
                (data, sep, device) = line.partition(">")
                if not device:
                    continue

                self.devices[device] = {}
                for pair in data.split():
                    try:
                        (key, value) = pair.split("=")
                    except ValueError:
                        continue

                    self.devices[device][key] = value[1:-1] # strip off quotes

    def __getitem__(self, key):
        return self.devices[key]

    def get(self, key, default=None):
        return self.devices.get(key, default)


class CryptTab(object):
    """ Dictionary-like interface to crypttab entries with map name keys """
    def __init__(self, devicetree, blkidTab=None, chroot=""):
        self.devicetree = devicetree
        self.blkidTab = blkidTab
        self.chroot = chroot
        self.mappings = {}

    def parse(self, chroot=""):
        """ Parse /etc/crypttab from an existing installation. """
        if not chroot or not os.path.isdir(chroot):
            chroot = ""

        path = "%s/etc/crypttab" % chroot
        log.debug("parsing %s" % path)
        with open(path) as f:
            if not self.blkidTab:
                try:
                    self.blkidTab = BlkidTab(chroot=chroot)
                    self.blkidTab.parse()
                except Exception:
                    self.blkidTab = None

            for line in f.readlines():
                (line, pound, comment) = line.partition("#")
                fields = line.split()
                if not 2 <= len(fields) <= 4:
                    continue
                elif len(fields) == 2:
                    fields.extend(['none', ''])
                elif len(fields) == 3:
                    fields.append('')

                (name, devspec, keyfile, options) = fields

                # resolve devspec to a device in the tree
                device = self.devicetree.resolveDevice(devspec,
                                                       blkidTab=self.blkidTab)
                if device:
                    self.mappings[name] = {"device": device,
                                           "keyfile": keyfile,
                                           "options": options}

    def populate(self):
        """ Populate the instance based on the device tree's contents. """
        for device in self.devicetree.devices.values():
            # XXX should we put them all in there or just the ones that
            #     are part of a device containing swap or a filesystem?
            #
            #       Put them all in here -- we can filter from FSSet
            if device.format.type != "luks":
                continue

            key_file = device.format.keyFile
            if not key_file:
                key_file = "none"

            options = device.format.options
            if not options:
                options = ""

            self.mappings[device.format.mapName] = {"device": device,
                                                    "keyfile": key_file,
                                                    "options": options}

    def crypttab(self):
        """ Write out /etc/crypttab """
        crypttab = ""
        for name in self.mappings:
            entry = self[name]
            crypttab += "%s UUID=%s %s %s\n" % (name,
                                                entry['device'].format.uuid,
                                                entry['keyfile'],
                                                entry['options'])
        return crypttab

    def __getitem__(self, key):
        return self.mappings[key]

    def get(self, key, default=None):
        return self.mappings.get(key, default)
