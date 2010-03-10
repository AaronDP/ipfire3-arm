#
# timezone.py - timezone install data
#
# Copyright 2001 Red Hat, Inc.
#
# This software may be freely redistributed under the terms of the GNU
# library public license.
#
# You should have received a copy of the GNU Library Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import shutil

import logging
log = logging.getLogger("pomona")

def bool(val):
    if val: return "true"
    return "false"

class Timezone:
    def write(self, instPath):
        fromFile = instPath + "/usr/share/zoneinfo/" + self.tz

        try:
            shutil.copyfile(fromFile, instPath + "/etc/localtime")
        except OSError, (errno, msg):
            log.error("Error copying timezone (from %s): %s" % (fromFile, msg))

        f = open(instPath + "/etc/sysconfig/clock", "w")

        f.write('ZONE="%s"\n' % self.tz)
        f.write("UTC=%s\n" % bool(self.utc))
        f.write("ARC=%s\n" % bool(self.arc))

        f.close()

    def getTimezoneInfo(self):
        return (self.tz, self.utc, self.arc)

    def setTimezoneInfo(self, timezone, asUtc = 0, asArc = 0):
        self.tz = timezone
        self.utc = asUtc
        self.arc = asArc

    def __init__(self):
        self.tz = "America/New_York"
        self.utc = 0
        self.arc = 0
