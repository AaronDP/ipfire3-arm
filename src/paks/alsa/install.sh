#!/bin/bash
. /opt/pakfire/lib/functions.sh

extract_files

touch /etc/asound.state
ln -sf  ../init.d/alsa /etc/rc.d/rc3.d/S65alsa
ln -sf  ../init.d/alsa /etc/rc.d/rc0.d/K35alsa
ln -sf  ../init.d/alsa /etc/rc.d/rc6.d/K35alsa
