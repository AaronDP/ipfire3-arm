#
# progress_text.py: text mode install/upgrade progress dialog
#
# Copyright 2001-2007 Red Hat, Inc.
#
# This software may be freely redistributed under the terms of the GNU
# library public license.
#
# You should have received a copy of the GNU Library Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
from constants import *
from snack import *
from pyfire.translate import _

import logging
log = logging.getLogger("pomona")

def strip_markup(text):
    if text.find("<") == -1:
        return text
    r = ""
    inTag = False
    for c in text:
        if c == ">" and inTag:
            inTag = False
            continue
        elif c == "<" and not inTag:
            inTag = True
            continue
        elif not inTag:
            r += c
    return r

class InstallProgressWindow:
    def __init__(self, screen):
        self.screen = screen
        self.drawn = False

        self.pct = 0

    def __del__ (self):
        if self.drawn:
            self.screen.popWindow ()

    def _setupScreen(self):
        screen = self.screen

        self.grid = GridForm(self.screen, _("File Installation"), 1, 6)

        self.width = 65
        self.progress = Scale(self.width, 100)
        self.grid.add (self.progress, 0, 1, (0, 1, 0, 0))

        self.label = Label("")
        self.grid.add(self.label, 0, 2, (0, 1, 0, 0), anchorLeft = 1)

        self.info = Textbox(self.width, 4, "", wrap = 1)
        self.grid.add(self.info, 0, 3, (0, 1, 0, 0))

        self.grid.draw()
        screen.refresh()
        self.drawn = True

    def processEvents(self):
        if not self.drawn:
            return
        self.grid.draw()
        self.screen.refresh()

    def setShowPercentage(self, val):
        pass

    def get_fraction(self):
        return self.pct

    def set_fraction(self, pct):
        if not self.drawn:
            self._setupScreen()

        self.progress.set(int(pct * 100))
        self.pct = pct
        self.processEvents()

    def set_label(self, txt):
        if not self.drawn:
            self._setupScreen()

        self.info.setText(strip_markup(txt))
        self.processEvents()

    def set_text(self, txt):
        if not self.drawn:
            self._setupScreen()

        if len(txt) > self.width:
            txt = txt[:self.width]
        else:
            spaces = (self.width - len(txt)) / 2
            txt = (" " * spaces) + txt

        self.label.setText(strip_markup(txt))
        self.processEvents()

class setupForInstall:
    def __call__(self, screen, pomona):
        if pomona.dir == DISPATCH_BACK:
            pomona.id.setInstallProgressClass(None)
            return INSTALL_BACK

        pomona.id.setInstallProgressClass(InstallProgressWindow(screen))
        return INSTALL_OK
