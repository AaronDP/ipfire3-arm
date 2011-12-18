#!/bin/bash

version=${1}
revision=${2}

if [ -z "${version}" ] || [ -z "${revision}" ]; then
	echo "Usage ${0}: <version> <revision>" >&2
	exit 1
fi

export_dir=mstpd-${version}-svn${revision}
rm -rf ${export_dir}

set -x

svn export http://svn.code.sf.net/p/mstpd/code/trunk ${export_dir}
tar cfz mstpd-${version}-svn${revision}.tar.gz ${export_dir}
rm -rf ${export_dir}

exit 0
