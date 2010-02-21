#!/usr/bin/python

import ctypes
import fcntl
import os
import select
import shutil
import subprocess
import sys
import time

from constants import *
from exception import *
from logger import getLog

_libc = ctypes.cdll.LoadLibrary(None)
_errno = ctypes.c_int.in_dll(_libc, "errno")
_libc.personality.argtypes = [ctypes.c_ulong]
_libc.personality.restype = ctypes.c_int
_libc.unshare.argtypes = [ctypes.c_int,]
_libc.unshare.restype = ctypes.c_int
CLONE_NEWNS = 0x00020000

# taken from sys/personality.h
PER_LINUX32=0x0008
PER_LINUX=0x0000
personality_defs = {
	'linux64': PER_LINUX,
	'linux32': PER_LINUX32,
}

def touch(filename):
	getLog().debug("touching file: %s" % filename)
	f = open(filename, "w")
	f.close()

def mkdir(*args):
	for dirName in args:
		getLog().debug("ensuring that dir exists: %s" % dirName)
		if not os.path.exists(dirName):
			try:
				getLog().debug("creating dir: %s" % dirName)
				os.makedirs(dirName)
			except OSError, e:
				getLog().exception("Could not create dir %s. Error: %s" % (dirName, e))
				raise Error, "Could not create dir %s. Error: %s" % (dirName, e)

def rm(path, *args, **kargs):
	"""version os shutil.rmtree that ignores no-such-file-or-directory errors,
		and tries harder if it finds immutable files"""
	tryAgain = 1
	failedFilename = None
	getLog().debug("remove tree: %s" % path)
	while tryAgain:
		tryAgain = 0
		try:
			shutil.rmtree(path, *args, **kargs)
		except OSError, e:
			if e.errno == 2: # no such file or directory
				pass
			elif e.errno==1 or e.errno==13:
				tryAgain = 1
				if failedFilename == e.filename:
					raise
				failedFilename = e.filename
				os.system("chattr -R -i %s" % path)
			else:
				raise

def logOutput(fds, logger, returnOutput=1, start=0, timeout=0):
	output=""
	done = 0

	# set all fds to nonblocking
	for fd in fds:
		flags = fcntl.fcntl(fd, fcntl.F_GETFL)
		if not fd.closed:
			fcntl.fcntl(fd, fcntl.F_SETFL, flags| os.O_NONBLOCK)

	tail = ""
	while not done:
		if (time.time() - start)>timeout and timeout!=0:
			done = 1
			break

		i_rdy,o_rdy,e_rdy = select.select(fds,[],[],1) 
		for s in i_rdy:
			# slurp as much input as is ready
			input = s.read()
			if input == "":
				done = 1
				break
			if logger is not None:
				lines = input.split("\n")
				if tail:
					lines[0] = tail + lines[0]
				# we may not have all of the last line
				tail = lines.pop()
				for line in lines:
					if line == '': continue
					logger.debug(line)
				for h in logger.handlers:
					h.flush()
			if returnOutput:
				output += input
	if tail and logger is not None:
		logger.debug(tail)
	return output

# these are called in child process, so no logging
def condChroot(chrootPath):
    if chrootPath is not None:
        os.chdir(chrootPath)
        os.chroot(chrootPath)

def condChdir(cwd):
    if cwd is not None:
        os.chdir(cwd)

def condPersonality(per=None):
    if not per:
        return
    if personality_defs.get(per, None) is None:
        return
    res = _libc.personality(personality_defs[per])
    if res == -1:
        raise OSError(_errno.value, os.strerror(_errno.value))

def do(command, shell=False, chrootPath=None, cwd=None, timeout=0, raiseExc=True, returnOutput=0, personality=None, *args, **kargs):
	logger = kargs.get("logger", getLog())
	output = ""
	start = time.time()
	env = kargs.get("env", None)
	preexec = ChildPreExec(personality, chrootPath, cwd)

	if config["nice_level"]:
		command = "nice -n %d %s" % (config["nice_level"], command)

	try:
		child = None
		logger.debug("Executing command: %s" % command)
		child = subprocess.Popen(
			command, 
			shell=shell,
			bufsize=0, close_fds=True, 
			stdin=open("/dev/null", "r"), 
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			preexec_fn = preexec,
			env=env
		)
		
		# use select() to poll for output so we dont block
		output = logOutput([child.stdout, child.stderr], 
				logger, returnOutput, start, timeout)

	except:
		# kill children if they arent done
		if child is not None and child.returncode is None:
			os.killpg(child.pid, 9)
		try:
			if child is not None:
				os.waitpid(child.pid, 0)
		except:
			pass
		raise

	# wait until child is done, kill it if it passes timeout
	niceExit=1
	while child.poll() is None:
		if (time.time() - start)>timeout and timeout!=0:
			niceExit=0
			os.killpg(child.pid, 15)
		if (time.time() - start)>(timeout+1) and timeout!=0:
			niceExit=0
			os.killpg(child.pid, 9)

	if not niceExit:
		raise commandTimeoutExpired, ("Timeout(%s) expired for command:\n # %s\n%s" % (timeout, command, output))

	logger.debug("Child returncode was: %s" % str(child.returncode))
	if raiseExc and child.returncode:
		if returnOutput:
			raise Error, ("Command failed: \n # %s\n%s" % (command, output), child.returncode)
		else:
			raise Error, ("Command failed. See logs for output.\n # %s" % (command,), child.returncode)

	return output

class ChildPreExec(object):
	def __init__(self, personality, chrootPath, cwd):
		self.personality = personality
		self.chrootPath  = chrootPath
		self.cwd = cwd

	def __call__(self, *args, **kargs):
		os.setpgrp()
		condPersonality(self.personality)
		condChroot(self.chrootPath)
		condChdir(self.cwd)
