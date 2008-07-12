/*
 * isys.c
 *
 * Copyright (C) 2007  Red Hat, Inc.  All rights reserved.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <Python.h>

#include <stdio.h>
#include <dirent.h>
#include <errno.h>
#define u32 __u32
#include <ext2fs/ext2fs.h>
#include <fcntl.h>
#include <popt.h>
/* Need to tell loop.h what the actual dev_t type is. */
#undef dev_t
#if defined(__alpha) || (defined(__sparc__) && defined(__arch64__))
#define dev_t unsigned int
#else
#if defined(__x86_64__)
#define dev_t unsigned long
#else
#define dev_t unsigned short
#endif
#endif
#include <linux/loop.h>
#undef dev_t
#define dev_t dev_t
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/time.h>
#include <sys/utsname.h>
#include <sys/vfs.h>
#include <unistd.h>
#include <resolv.h>
#include <scsi/scsi.h>
#include <scsi/scsi_ioctl.h>
#include <sys/vt.h>
#include <sys/types.h>
#include <linux/fb.h>
#include <libintl.h>
#include <libgen.h>
#include <linux/major.h>
#include <linux/raid/md_u.h>
#include <linux/raid/md_p.h>
#include <signal.h>

#include <blkid/blkid.h>
#include <blkid/blkid_types.h>

#include "isys.h"
#include "imount.h"
#include "net.h"
#include "smp.h"
#include "lang.h"
#include "wireless.h"
#include "eddsupport.h"

#ifndef CDROMEJECT
#define CDROMEJECT 0x5309
#endif

static PyObject * doGetOpt(PyObject * s, PyObject * args);
/*static PyObject * doInsmod(PyObject * s, PyObject * args);
static PyObject * doRmmod(PyObject * s, PyObject * args);*/
static PyObject * doMount(PyObject * s, PyObject * args);
static PyObject * doUMount(PyObject * s, PyObject * args);
static PyObject * smpAvailable(PyObject * s, PyObject * args);
static PyObject * htAvailable(PyObject * s, PyObject * args);
static PyObject * doSwapon(PyObject * s, PyObject * args);
static PyObject * doSwapoff(PyObject * s, PyObject * args);
static PyObject * doLoSetup(PyObject * s, PyObject * args);
static PyObject * doUnLoSetup(PyObject * s, PyObject * args);
static PyObject * doLoChangeFd(PyObject * s, PyObject * args);
static PyObject * doDdFile(PyObject * s, PyObject * args);
static PyObject * doDevSpaceFree(PyObject * s, PyObject * args);
static PyObject * doLoadKeymap(PyObject * s, PyObject * args);
static PyObject * doClobberExt2(PyObject * s, PyObject * args);
static PyObject * doReadE2fsLabel(PyObject * s, PyObject * args);
static PyObject * doExt2Dirty(PyObject * s, PyObject * args);
static PyObject * doExt2HasJournal(PyObject * s, PyObject * args);
static PyObject * doEjectCdrom(PyObject * s, PyObject * args);
static PyObject * doVtActivate(PyObject * s, PyObject * args);
static PyObject * doisPsudoTTY(PyObject * s, PyObject * args);
static PyObject * doisVioConsole(PyObject * s);
static PyObject * doSync(PyObject * s, PyObject * args);
static PyObject * doisIsoImage(PyObject * s, PyObject * args);
static PyObject * getFramebufferInfo(PyObject * s, PyObject * args);
static PyObject * printObject(PyObject * s, PyObject * args);
static PyObject * py_bind_textdomain_codeset(PyObject * o, PyObject * args);
static PyObject * isWireless(PyObject * s, PyObject * args);
static PyObject * doProbeBiosDisks(PyObject * s, PyObject * args);
static PyObject * doGetBiosDisk(PyObject * s, PyObject * args);
static PyObject * doGetBlkidData(PyObject * s, PyObject * args);

static PyMethodDef isysModuleMethods[] = {
    { "ejectcdrom", (PyCFunction) doEjectCdrom, METH_VARARGS, NULL },
    { "e2dirty", (PyCFunction) doExt2Dirty, METH_VARARGS, NULL },
    { "e2hasjournal", (PyCFunction) doExt2HasJournal, METH_VARARGS, NULL },
    { "e2fslabel", (PyCFunction) doReadE2fsLabel, METH_VARARGS, NULL },
    { "e2fsclobber", (PyCFunction) doClobberExt2, METH_VARARGS, NULL },
    { "devSpaceFree", (PyCFunction) doDevSpaceFree, METH_VARARGS, NULL },
    { "lochangefd", (PyCFunction) doLoChangeFd, METH_VARARGS, NULL },
    { "losetup", (PyCFunction) doLoSetup, METH_VARARGS, NULL },
    { "unlosetup", (PyCFunction) doUnLoSetup, METH_VARARGS, NULL },
    { "ddfile", (PyCFunction) doDdFile, METH_VARARGS, NULL },
    { "getopt", (PyCFunction) doGetOpt, METH_VARARGS, NULL },
    { "mount", (PyCFunction) doMount, METH_VARARGS, NULL },
    { "smpavailable", (PyCFunction) smpAvailable, METH_VARARGS, NULL },
    { "htavailable", (PyCFunction) htAvailable, METH_VARARGS, NULL },
    { "umount", (PyCFunction) doUMount, METH_VARARGS, NULL },
    { "swapon",  (PyCFunction) doSwapon, METH_VARARGS, NULL },
    { "swapoff",  (PyCFunction) doSwapoff, METH_VARARGS, NULL },
    { "loadKeymap", (PyCFunction) doLoadKeymap, METH_VARARGS, NULL },
    { "vtActivate", (PyCFunction) doVtActivate, METH_VARARGS, NULL},
    { "isPsudoTTY", (PyCFunction) doisPsudoTTY, METH_VARARGS, NULL},
    { "isVioConsole", (PyCFunction) doisVioConsole, METH_NOARGS, NULL},
    { "sync", (PyCFunction) doSync, METH_VARARGS, NULL},
    { "isisoimage", (PyCFunction) doisIsoImage, METH_VARARGS, NULL},
    { "fbinfo", (PyCFunction) getFramebufferInfo, METH_VARARGS, NULL},
    { "printObject", (PyCFunction) printObject, METH_VARARGS, NULL},
    { "bind_textdomain_codeset", (PyCFunction) py_bind_textdomain_codeset, METH_VARARGS, NULL},
    { "isWireless", (PyCFunction) isWireless, METH_VARARGS, NULL },
    { "biosDiskProbe", (PyCFunction) doProbeBiosDisks, METH_VARARGS,NULL},
    { "getbiosdisk",(PyCFunction) doGetBiosDisk, METH_VARARGS,NULL},
    { "getblkid", (PyCFunction) doGetBlkidData, METH_VARARGS, NULL },
    { NULL, NULL, 0, NULL }
} ;

static PyObject * doDdFile(PyObject * s, PyObject * args) {
    int fd;
    int megs;
    char * ptr;
    int i;

    if (!PyArg_ParseTuple(args, "ii", &fd, &megs)) return NULL;

    ptr = calloc(1024 * 256, 1);

    while (megs--) {
	for (i = 0; i < 4; i++) {
	    if (write(fd, ptr, 1024 * 256) != 1024 * 256) {
		PyErr_SetFromErrno(PyExc_SystemError);
		free(ptr);
		return NULL;
	    }
	    sync();
	}
    }

    free(ptr);

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doUnLoSetup(PyObject * s, PyObject * args) {
    int loopfd;

    if (!PyArg_ParseTuple(args, "i", &loopfd)) return NULL;
    if (ioctl(loopfd, LOOP_CLR_FD, 0)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

/* XXX - msw */
#ifndef LOOP_CHANGE_FD
#define LOOP_CHANGE_FD	0x4C06
#endif

static PyObject * doLoChangeFd(PyObject * s, PyObject * args) {
    int loopfd;
    int targfd;

    if (!PyArg_ParseTuple(args, "ii", &loopfd, &targfd))
	return NULL;
    if (ioctl(loopfd, LOOP_CHANGE_FD, targfd)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doLoSetup(PyObject * s, PyObject * args) {
    int loopfd;
    int targfd;
    struct loop_info loopInfo;
    char * loopName;

    if (!PyArg_ParseTuple(args, "iis", &loopfd, &targfd, &loopName))
	return NULL;
    if (ioctl(loopfd, LOOP_SET_FD, targfd)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    memset(&loopInfo, 0, sizeof(loopInfo));
    strncpy(loopInfo.lo_name, basename(loopName), 63);

    if (ioctl(loopfd, LOOP_SET_STATUS, &loopInfo)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doGetOpt(PyObject * s, PyObject * pyargs) {
    PyObject * argList, * longArgs, * strObject;
    PyObject * retList, * retArgs;
    char * shortArgs;
    struct poptOption * options;
    int numOptions, i, rc;
    char * ch;
    poptContext optCon;
    char * str;
    char * error;
    const char ** argv;
    char strBuf[3];

    if (!PyArg_ParseTuple(pyargs, "OsO", &argList, &shortArgs, &longArgs))
	return NULL;

    if (!(PyList_Check(argList))) {
	PyErr_SetString(PyExc_TypeError, "list expected");
    }
    if (!(PyList_Check(longArgs))) {
	PyErr_SetString(PyExc_TypeError, "list expected");
    }

    numOptions = PyList_Size(longArgs);
    for (ch = shortArgs; *ch; ch++)
	if (*ch != ':') numOptions++;

    options = alloca(sizeof(*options) * (numOptions + 1));

    ch = shortArgs;
    numOptions = 0;
    while (*ch) {
        options[numOptions].shortName = *ch++;
        options[numOptions].longName = NULL;
	options[numOptions].val = 0;
	options[numOptions].descrip = NULL;
	options[numOptions].argDescrip = NULL;
	options[numOptions].arg = NULL;
	if (*ch == ':') {
	    options[numOptions].argInfo = POPT_ARG_STRING;
	    ch++;
	} else {
	    options[numOptions].argInfo = POPT_ARG_NONE;
	}

	options[numOptions].val = numOptions + 1;

	numOptions++;
    }

    for (i = 0; i < PyList_Size(longArgs); i++) {
        options[numOptions].shortName = 0;
	options[numOptions].val = 0;
	options[numOptions].descrip = NULL;
	options[numOptions].argDescrip = NULL;
	options[numOptions].arg = NULL;

        strObject = PyList_GetItem(longArgs, i);
	str = PyString_AsString(strObject);
	if (!str) return NULL;

	if (str[strlen(str) - 1] == '=') {
	    str = strcpy(alloca(strlen(str) + 1), str);
	    str[strlen(str) - 1] = '\0';
	    options[numOptions].argInfo = POPT_ARG_STRING;
	} else {
	    options[numOptions].argInfo = POPT_ARG_NONE;
	}

	options[numOptions].val = numOptions + 1;
	options[numOptions].longName = str;

	numOptions++;
    }

    memset(options + numOptions, 0, sizeof(*options));

    argv = alloca(sizeof(*argv) * (PyList_Size(argList) + 1));
    for (i = 0; i < PyList_Size(argList); i++) {
        strObject = PyList_GetItem(argList, i);
	str = PyString_AsString(strObject);
	if (!str) return NULL;

	argv[i] = str;
    }

    argv[i] = NULL;

    optCon = poptGetContext("", PyList_Size(argList), argv,
			    options, POPT_CONTEXT_KEEP_FIRST);
    retList = PyList_New(0);
    retArgs = PyList_New(0);

    while ((rc = poptGetNextOpt(optCon)) >= 0) {
	const char * argument;

	rc--;

	if (options[rc].argInfo == POPT_ARG_STRING)
	    argument = poptGetOptArg(optCon);
	else
	    argument = NULL;

	if (options[rc].longName) {
	    str = alloca(strlen(options[rc].longName) + 3);
	    sprintf(str, "--%s", options[rc].longName);
	} else {
	    str = strBuf;
	    sprintf(str, "-%c", options[rc].shortName);
	}

	if (argument) {
	    argument = strcpy(alloca(strlen(argument) + 1), argument);
	    PyList_Append(retList,
			    Py_BuildValue("(ss)", str, argument));
	} else {
	    PyList_Append(retList, Py_BuildValue("(ss)", str, ""));
	}
    }

    if (rc < -1) {
	i = strlen(poptBadOption(optCon, POPT_BADOPTION_NOALIAS)) +
	    strlen(poptStrerror(rc));

	error = alloca(i) + 50;

	sprintf(error, "bad argument %s: %s\n",
		poptBadOption(optCon, POPT_BADOPTION_NOALIAS),
		poptStrerror(rc));

	PyErr_SetString(PyExc_TypeError, error);
	return NULL;
    }

    argv = (const char **) poptGetArgs(optCon);
    for (i = 0; argv && argv[i]; i++) {
	PyList_Append(retArgs, PyString_FromString(argv[i]));
    }

    poptFreeContext(optCon);

    return Py_BuildValue("(OO)", retList, retArgs);
}

static PyObject * doUMount(PyObject * s, PyObject * args) {
    char * fs;

    if (!PyArg_ParseTuple(args, "s", &fs)) return NULL;

    if (umount(fs)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doMount(PyObject * s, PyObject * args) {
    char *fs, *device, *mntpoint, *flags = NULL;
    int rc;

    if (!PyArg_ParseTuple(args, "sss|z", &fs, &device, &mntpoint,
			  &flags)) return NULL;

    rc = doPwMount(device, mntpoint, fs, flags);
    if (rc == IMOUNT_ERR_ERRNO)
	PyErr_SetFromErrno(PyExc_SystemError);
    else if (rc) {
        PyObject *tuple = PyTuple_New(2);

        PyTuple_SetItem(tuple, 0, PyInt_FromLong(rc));
        PyTuple_SetItem(tuple, 1, PyString_FromString("mount failed"));
        PyErr_SetObject(PyExc_SystemError, tuple);
    }

    if (rc) return NULL;

    Py_INCREF(Py_None);
    return Py_None;
}

#define BOOT_SIGNATURE	0xaa55	/* boot signature */
#define BOOT_SIG_OFFSET	510	/* boot signature offset */

int swapoff(const char * path);
int swapon(const char * path, int priorty);

static PyObject * doSwapoff (PyObject * s, PyObject * args) {
    char * path;

    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;

    if (swapoff (path)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doSwapon (PyObject * s, PyObject * args) {
    char * path;

    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;

    if (swapon (path, 0)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * smpAvailable(PyObject * s, PyObject * args) {
    if (!PyArg_ParseTuple(args, "")) return NULL;

    return Py_BuildValue("i", detectSMP());
}

static PyObject * htAvailable(PyObject * s, PyObject * args) {
    if (!PyArg_ParseTuple(args, "")) return NULL;

    return Py_BuildValue("i", detectHT());
}

void init_isys(void) {
    PyObject * m, * d;

    m = Py_InitModule("_isys", isysModuleMethods);
    d = PyModule_GetDict(m);

    PyDict_SetItemString(d, "MIN_RAM", PyInt_FromLong(MIN_RAM));
    PyDict_SetItemString(d, "EARLY_SWAP_RAM", PyInt_FromLong(EARLY_SWAP_RAM));
}

static int get_bits(unsigned long long v) {
    int  b = 0;

    if ( v & 0xffffffff00000000LLU ) { b += 32; v >>= 32; }
    if ( v & 0xffff0000LLU ) { b += 16; v >>= 16; }
    if ( v & 0xff00LLU ) { b += 8; v >>= 8; }
    if ( v & 0xf0LLU ) { b += 4; v >>= 4; }
    if ( v & 0xcLLU ) { b += 2; v >>= 2; }
    if ( v & 0x2LLU ) b++;

    return v ? b + 1 : b;
}

static PyObject * doDevSpaceFree(PyObject * s, PyObject * args) {
    char * path;
    struct statfs sb;
    unsigned long long size;

    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;

    if (statfs(path, &sb)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    /* Calculate a saturated addition to prevent oveflow. */
    if ( get_bits(sb.f_bfree) + get_bits(sb.f_bsize) <= 64 )
        size = (unsigned long long)sb.f_bfree * sb.f_bsize;
    else
        size = ~0LLU;

    return PyLong_FromUnsignedLongLong(size>>20);
}

static PyObject * doLoadKeymap (PyObject * s, PyObject * args) {
    char * keymap;
    int ret;

    if (!PyArg_ParseTuple(args, "s", &keymap)) return NULL;

    ret = isysLoadKeymap (keymap);
    if (ret) {
	errno = -ret;
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doClobberExt2 (PyObject * s, PyObject * args) {
    char * device;
    ext2_filsys fsys;
    struct ext2_super_block sb;
    int rc;

    if (!PyArg_ParseTuple(args, "s", &device)) return NULL;

    rc = ext2fs_open(device, EXT2_FLAG_FORCE, 0, 0, unix_io_manager, &fsys);

    if (rc) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    memset(&sb, 0, sizeof(struct ext2_super_block));
    rc = ext2fs_initialize (device, 0, &sb, unix_io_manager, &fsys);
    if (rc) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    ext2fs_close(fsys);

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doReadE2fsLabel(PyObject * s, PyObject * args) {
    char * device;
    ext2_filsys fsys;
    char buf[50];
    int rc;

    if (!PyArg_ParseTuple(args, "s", &device)) return NULL;

    rc = ext2fs_open(device, EXT2_FLAG_FORCE, 0, 0, unix_io_manager,
		     &fsys);
    if (rc) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    memset(buf, 0, sizeof(buf));
    strncpy(buf, fsys->super->s_volume_name,
	    sizeof(fsys->super->s_volume_name));

    ext2fs_close(fsys);

    return Py_BuildValue("s", buf);
}

static PyObject * doExt2Dirty(PyObject * s, PyObject * args) {
    char * device;
    ext2_filsys fsys;
    int rc;
    int clean;

    if (!PyArg_ParseTuple(args, "s", &device)) return NULL;

    rc = ext2fs_open(device, EXT2_FLAG_FORCE, 0, 0, unix_io_manager,
		     &fsys);
    if (rc) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    clean = fsys->super->s_state & EXT2_VALID_FS;

    ext2fs_close(fsys);

    return Py_BuildValue("i", !clean);
}

static PyObject * doExt2HasJournal(PyObject * s, PyObject * args) {
    char * device;
    ext2_filsys fsys;
    int rc;
    int hasjournal;

    if (!PyArg_ParseTuple(args, "s", &device)) return NULL;
    rc = ext2fs_open(device, EXT2_FLAG_FORCE, 0, 0, unix_io_manager,
		     &fsys);
    if (rc) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    hasjournal = fsys->super->s_feature_compat & EXT3_FEATURE_COMPAT_HAS_JOURNAL;

    ext2fs_close(fsys);

    return Py_BuildValue("i", hasjournal);
}

static PyObject * doEjectCdrom(PyObject * s, PyObject * args) {
    int fd;

    if (!PyArg_ParseTuple(args, "i", &fd)) return NULL;

    if (ioctl(fd, CDROMEJECT, 1)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doVtActivate(PyObject * s, PyObject * args) {
    int vtnum;

    if (!PyArg_ParseTuple(args, "i", &vtnum)) return NULL;

    if (ioctl(0, VT_ACTIVATE, vtnum)) {
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doisPsudoTTY(PyObject * s, PyObject * args) {
    int fd;
    struct stat sb;

    if (!PyArg_ParseTuple(args, "i", &fd)) return NULL;
    fstat(fd, &sb);

    /* XXX close enough for now */
    return Py_BuildValue("i", ((major(sb.st_rdev) >= 136) && (major(sb.st_rdev) <= 143)));
}

static PyObject * doisVioConsole(PyObject * s) {
    return Py_BuildValue("i", isVioConsole());
}

static PyObject * doSync(PyObject * s, PyObject * args) {
    int fd;

    if (!PyArg_ParseTuple(args, "", &fd)) return NULL;
    sync();

    Py_INCREF(Py_None);
    return Py_None;
}

int fileIsIso(const char * file);

static PyObject * doisIsoImage(PyObject * s, PyObject * args) {
    char * fn;
    int rc;

    if (!PyArg_ParseTuple(args, "s", &fn)) return NULL;

    rc = fileIsIso(fn);

    return Py_BuildValue("i", rc);
}

static PyObject * getFramebufferInfo(PyObject * s, PyObject * args) {
    int fd;
    struct fb_var_screeninfo fb;

    fd = open("/dev/fb0", O_RDONLY);
    if (fd == -1) {
	Py_INCREF(Py_None);
	return Py_None;
    }

    if (ioctl(fd, FBIOGET_VSCREENINFO, &fb)) {
	close(fd);
	PyErr_SetFromErrno(PyExc_SystemError);
	return NULL;
    }

    close(fd);

    return Py_BuildValue("(iii)", fb.xres, fb.yres, fb.bits_per_pixel);
}

static PyObject * isWireless(PyObject * s, PyObject * args) {
    char *dev;
    int ret;

    if (!PyArg_ParseTuple(args, "s", &dev))
	return NULL;

    ret = is_wireless_interface(dev);

    return Py_BuildValue("i", ret);
}

static PyObject * printObject (PyObject * o, PyObject * args) {
    PyObject * obj;
    char buf[256];

    if (!PyArg_ParseTuple(args, "O", &obj))
	return NULL;

    snprintf(buf, 256, "<%s object at %lx>", obj->ob_type->tp_name,
	     (long) obj);

    return PyString_FromString(buf);
}

static PyObject *
py_bind_textdomain_codeset(PyObject * o, PyObject * args) {
    char *domain, *codeset, *ret;

    if (!PyArg_ParseTuple(args, "ss", &domain, &codeset))
	return NULL;

    ret = bind_textdomain_codeset(domain, codeset);

    if (ret)
	return PyString_FromString(ret);

    PyErr_SetFromErrno(PyExc_SystemError);
    return NULL;
}

static PyObject * doProbeBiosDisks(PyObject * s, PyObject * args) {
    if (!PyArg_ParseTuple(args, "")) return NULL;


    return Py_BuildValue("i", probeBiosDisks());
}

static PyObject * doGetBiosDisk(PyObject * s, PyObject * args) {
    char *mbr_sig;
    char *diskname;

    if (!PyArg_ParseTuple(args, "s", &mbr_sig)) return NULL;

    if ((diskname = getBiosDisk(mbr_sig)))
        return Py_BuildValue("s", diskname);

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * doGetBlkidData(PyObject * s, PyObject * args) {
    char * dev, * key;
    blkid_cache cache;
    blkid_dev bdev = NULL;
    blkid_tag_iterate titer;
    const char * type, * data;

    if (!PyArg_ParseTuple(args, "ss", &dev, &key)) return NULL;

    blkid_get_cache(&cache, NULL);

    bdev = blkid_get_dev(cache, dev, BLKID_DEV_NORMAL);
    if (bdev == NULL)
        goto out;
    titer = blkid_tag_iterate_begin(bdev);
    while (blkid_tag_next(titer, &type, &data) >= 0) {
        if (!strcmp(type, key)) {
            blkid_tag_iterate_end(titer);
            return Py_BuildValue("s", data);
        }
    }
    blkid_tag_iterate_end(titer);

 out:
    Py_INCREF(Py_None);
    return Py_None;
}

/* vim:set shiftwidth=4 softtabstop=4: */
