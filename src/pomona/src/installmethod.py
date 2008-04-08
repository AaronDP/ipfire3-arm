#
# installmethod.py - Base class for install methods
#
# Copyright 1999-2002 Red Hat, Inc.
#
# This software may be freely redistributed under the terms of the GNU
# library public license.
#
# You should have received a copy of the GNU Library Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import os
import string
from constants import *

import logging
log = logging.getLogger("pomona")

class FileCopyException(Exception):
	def __init__(self, s=""):
		self.args = s

class InstallMethod:
	def protectedPartitions(self):
		return None

	def getTempPath(self):
		root = self.rootPath
		pathlist = [ "/var/tmp", "/tmp", "/." ]
		tmppath = None
		for p in pathlist:
			if (os.access(root + p, os.X_OK)):
				tmppath = root + p + "/"
				break

		if tmppath is None:
			log.warning("Unable to find temp path, going to use ramfs path")
			return "/tmp/"

		return tmppath

	def getFilename(self, filename, callback=None, destdir=None, retry=1):
		pass

	def systemUmounted(self):
		pass

	def systemMounted(self, fstab, mntPoint):
		pass

	def filesDone(self):
		pass

	def unlinkFilename(self, fullName):
		pass

	def __init__(self, rootpath, intf):
		self.rootPath = rootpath
		self.intf = intf

	def getMethodUri(self):
		pass
	
	def setMethodUri(self, uri):
		pass
	
	def getSourcePath(self):
		pass
	
	def umountMedia(self):
		pass
	
	def doPreInstall(self, pomona):
		pass
	
	def doPostInstall(self, pomona):
		pass
	
	def ejectMedia(self):
		pass
	
	def badPackageError(self, pkgname):
		pass

	# this is very very very late.  it's even after kickstart %post.
	# only use this if you really know what you're doing.
	def postAction(self, pomona):
		pass

# This handles any cleanup needed for the method.  It occurs *very* late
# and is mainly used for unmounting media and ejecting the CD.  If we're on
# a kickstart install, don't eject the CD since there's a command to do that
# if the user wants.
def doMethodComplete(pomona):
	pomona.method.filesDone()

	pomona.method.ejectMedia()

	mtab = "/dev/root / ext3 ro 0 0\n"
	for ent in pomona.id.fsset.entries:
		if ent.mountpoint == "/":
			mtab = "/dev/root / %s ro 0 0\n" %(ent.fsystem.name,)

	f = open(pomona.rootPath + "/etc/mtab", "w+")
	f.write(mtab)
	f.close()
