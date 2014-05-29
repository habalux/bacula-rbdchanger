#!/usr/bin/python

import os,sys
import json
import glob
import subprocess

import rados
import rbd

import pwd, grp

def print_help():
	print "Usage: %s <conffile> <command> <slot> <path> <driveindex>"%(sys.argv[0])

class RBDChanger(object):
	def __init__(self, conffile):
		self.conffile = conffile
		self.load_config()
	
	def load_config(self):
		d = json.loads(open(self.conffile).read() )
		self.config = d
		#print d

	def __run_command(self, cmd):
		p1 = subprocess.Popen(["sudo"] + cmd, stdout=subprocess.PIPE)
		p1.wait()
		
		output = p1.communicate()
		#print output
		return (p1.returncode, output[0])

	def __getmapped(self):
		cmd = [
			"/usr/bin/rbd",
			"showmapped",
			"--pool", self.config['pool'],
			'--format','json'
		]
		#print cmd
		status,output = self.__run_command(cmd)
		j = json.loads(output)
		return j

	def __open_rados(self):
		rconn = rados.Rados(conffile='/etc/ceph/ceph.conf')
		rconn.connect()
		return rconn


	def __getslots(self):
		cmd = [
			"/usr/bin/rbd",
			"ls",
			"--pool", self.config['pool'],
			"--format","json"
		]
		#print cmd
		status,output = self.__run_command(cmd)
		output = json.loads(output)
		return output

	def __getmapped_slot(self, slot):
		mapped_device = None
		mapped = self.__getmapped()
		#print mapped
		for mapid,mapped in mapped.items():
			#print mapid
			#print mapped['device']
			m_int = int(mapped['name'].replace(self.config['prefix'],''))
			#print m_int, slot
			if m_int == slot:
				#print "Already mapped"
				
				return mapped
		return None

	def __map(self, slot):
		cmd = [
			'rbd',
			'map',
			'%s%.5d'%(self.config['prefix'], slot),
			'--pool', self.config['pool']
			]
		status,output = self.__run_command(cmd)
		if status != 0:
			print output
			raise RuntimeError("Error status %s from '%s'"%(status, " ".join(cmd)))

	def __unmap(self, device):
		cmd = [
			'rbd',
			'unmap',
			device
			]
		status,output = self.__run_command(cmd)
		if status != 0:
			print output
			raise RuntimeError("Error status %s from '%s'"%(status, " ".join(cmd)))

	def labelnew(self, slot, path, driveindex):
		rconn = self.__open_rados()
		print "Pool: %s"%(self.config['pool'])
		ioctx = rconn.open_ioctx(str(self.config['pool']))
		try:
			counter = ioctx.read('counter')
		except rados.ObjectNotFound:
			counter = "0"
			#ioctx.write_full('counter','0')

		counter = str( int(counter) + 1 )
		ioctx.write_full('counter',str(counter))

		label = "%s%.5d"%(self.config['prefix'], int(counter))
		print "New label: %s"%(label)

		rbdconn = rbd.RBD()
		try:
			rbdconn.create(ioctx, str(label), int(self.config['imagesize'])*1024*1024)
		except rbd.ImageExists:
			print "Image '%s' already exists! Skipping!"%(label)

		# Map image to rbd
		self.__map(int(counter))

		# Format image
		if self.config['imageformat'] == 'ext4':
			cmd = [
				'mke2fs', '-j', '-O','extents',
				'-L', str(label),
				'/dev/rbd/%s/%s'%(self.config['pool'], label)
			]
		else:
			raise ValueError("Unknown image format '%s'"%(self.config['imageformat']))

		status,output = self.__run_command(cmd)
		if status != 0:
			raise RuntimeError("Error status %d from '%s'"%(status, " ".join(cmd)))

		# Mount and add datafile
		cmd = [
			'mount', '/dev/rbd/%s/%s'%(self.config['pool'], label),
			self.config['image_staging_dir']
		]

		status, output = self.__run_command(cmd)
		if status != 0:
			raise RuntimeError("Error status %d from '%s'"%(status, " ".join(cmd)))

		uid = pwd.getpwnam("bacula").pw_uid
		gid = grp.getgrnam("tape").gr_gid

		# Write dummy data file
		datafile_path = os.path.join(self.config['image_staging_dir'], 'data')
		datafile = open( datafile_path ,'w' )
		datafile.close()

		os.chown(datafile_path, uid, gid)
		

		# Write label just in case
		labelfile_path = os.path.join(self.config['image_staging_dir'], 'barcode')
		labelfile = open( labelfile_path, 'w')
		labelfile.write(label)
		labelfile.write("\n")
		labelfile.close()

		os.chown(datafile_path, uid, gid)

		# unmount
		cmd = [
			'umount', self.config['image_staging_dir']
		]

		status, output = self.__run_command(cmd)
		if status != 0:
			raise RuntimeError("Error status %d from '%s'"%(status, " ".join(cmd)))

		# Unmap
		mapped = self.__getmapped_slot(int(counter))
		assert mapped != None

		mapped_device = mapped['device']
		assert mapped_device != None
		self.__unmap(mapped_device)

		print "Image %s created"%(label)



	def unload(self, slot, path, driveindex):
		mountpath = path
		slot = int(slot)
		is_mapped = False
		mapped_device = None
		# Is it mapped already?
		mapped = self.__getmapped_slot(slot)
		if not mapped:
			return

		mapped_device = mapped['device']
		mountpoint_check = self.config['path']%(int(driveindex))
		# unmount
		cmd = [
			'umount',
			mountpoint_check
		]

		status,output = self.__run_command(cmd)
		if status != 0:
			print output
			raise RuntimeError("Error status %d from '%s'"%(status, " ".join(cmd)))

		assert mapped_device != None
		self.__unmap(mapped_device)
		print "Device %s unmapped"%(mapped_device)

	def load(self, slot, path, driveindex):
		slot = int(slot)
		is_mapped = False
		mapped_device = None

		# Is it mapped already?
		mapped = self.__getmapped_slot(slot)
		if mapped:
			is_mapped = True
		else:
			self.__map(slot)
			mapped = self.__getmapped_slot(slot)

		assert mapped != None
		assert mapped.has_key('device')
		# Is the directory already mounted?
		mountpoint_check = self.config['path']%(int(driveindex))
		cmd = [
			'mountpoint',
			mountpoint_check
		]
		status,output = self.__run_command(cmd)
		if status != 1:
			print status, output
			raise RuntimeError("Mountpoint '%s' is already mounted!"%(mountpoint_check))

		cmd = [
			'mount',
			mapped['device'],
			mountpoint_check
			]
		status,output = self.__run_command(cmd)
		if status != 0:
			print output
			raise RuntimeError("Error status %d from '%s'"%(status, " ".join(cmd)))

	def list_volumes2(self, slot, path, driveindex):
		slot = int(slot)
		if slot == 0:
			slot = 1
		# Is it mounted?
		barcode = open( os.path.join(self.config['path']%(int(driveindex)), 'barcode')).read()
		open("/tmp/slotlist",'w').write(str(sys.argv))
		print "%d:%s"%(slot, barcode.strip())
		return

	def list_volumes(self, slot, path, driveindex):
		rconn = self.__open_rados()
		ioctx = rconn.open_ioctx(str(self.config['pool']))
		rbdconn = rbd.RBD()
		images = [str(l) for l in rbdconn.list(ioctx) if l.startswith(self.config['prefix'])]
		for i in images:
			#print i
			slotnum = i.replace(str(self.config['prefix']),'')
			#print slotnum
			print "%d:%s"%(int(slotnum), i)

	def list_slots(self, slot, path, driveindex):
		slots = self.__getslots()
		slots.sort()
		for s in slots:
			print int(s.replace(self.config['prefix'],''))

	def slots(self, slot, path, driveindex):
		slots = self.__getslots()
		slots.sort()
		print len(slots)
		#for s in slots:
		#	print int(s.replace('bacula',''))
		#print slots

	def loaded(self, slot, path, driveindex):
		slot = int(slot)
		mapped = self.__getmapped()
		#print mapped
		if mapped == None:
			return

		mountpoint_check = self.config['path']%(int(driveindex))
		cmd = [
			'mountpoint',
			mountpoint_check
		]
		status,output = self.__run_command(cmd)
		if status != 0:
			# Not mounted
			return
			#print status, output
			#raise RuntimeError("Mountpoint '%s' is already mounted!"%(mountpoint_check))

		#print "It is mounted"
		#assert mapped.has_key('device')
		#assert mapped.has_key('name')
		# Is it mounted?
		mounts = open('/proc/mounts').readlines()
		for l in mounts:
			line = l.split(' ')
			#print repr(line)
			if line[1].strip() == mountpoint_check:
				#print "Mounted!"
				rbd_device = line[0].strip()
				# Find out which image is mapped to this device
				for m,md in mapped.items():
					#print md
					if md['device'] == rbd_device:
						print "%d"%( int(md['name'].replace(self.config['prefix'], '')) )

if __name__ == "__main__":
	if len(sys.argv) < 2:
		print_help()
		sys.exit(1)

	changer = RBDChanger(conffile=sys.argv[1])
	command = sys.argv[2]

	if command == 'labelnew':
		changer.labelnew(None,None,None)
		sys.exit(0)

	slot = sys.argv[3]
	path = sys.argv[4]
	driveindex = sys.argv[5]

	if command == 'list':
		changer.list_volumes(slot, path, driveindex)
	elif command == 'load':
		changer.load(slot, path, driveindex)
	elif command == 'unload':
		changer.unload(slot, path, driveindex)
	elif command == 'slots':
		changer.slots(slot, path, driveindex)
	elif command == 'loaded':
		changer.loaded(slot, path, driveindex)
	else:
		print "Unknown operation '%s'"%(sys.argv[2])
		sys.exit(1)
