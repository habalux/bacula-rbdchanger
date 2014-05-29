bacula-rbdchanger
=================

RBD (Ceph) virtual image changer for Bacula

Disclaimer
=================

This is an early work in progress script, so it is NOT guaranteed to work properly on any other system than mine. Be warned!


Usage
-----------------

You need the ceph-common package to get python 

1. Copy the files *rbdchanger.py* and *rbdchanger1.conf* to /etc/bacula/
2. Modify rbdchanger1.conf to accommodate your settings
3. Create the rbd pool: ```rados mkpool bacula```
4. Create the mount point for image staging: ```mkdir -p /mnt/bacula```
5. Modify your bacula-sd.conf like this:

```
Autochanger {
  Name = rbdchanger1;
  Device = rbdchanger1_drive0;
  Changer Command = "/etc/bacula/rbdchanger.py %c %o %S %a %d";
  Changer Device = "/etc/bacula/rbdchanger1.conf";
}

Device {
  Name = rbdchanger1_drive0
  DriveIndex = 0
  Media Type = File;
  Device Type = File;
  Autochanger = yes;
  Archive Device = /var/lib/bacula/rbdchanger1/drive0/data;
  Label Media = yes;
  Random Access = yes;
  Automatic Mount = yes;
  Removable Media = yes;
  Always Open = yes;
}
```

6. And you bacula-dir.conf like this:
```
Storage {
  Name = File
# Do not use "localhost" here    
  Address = localhost                # N.B. Use a fully qualified name here
  SDPort = 9103
  Password = "role3wACJofhYPeaYHUdcg-Q12ZugznwH"
  Device = rbdchanger1_drive0
  #Device = FileStorage
  Media Type = File;
  Autochanger = yes;
}
```
7. Run ```/etc/bacula/rbdchanger.py /etc/bacula/rbdchanger1.conf labelnew```
   - It should create cephVolume00001 for you
   - Make a couple more images for fun
8. Start bconsole and give the command "label barcodes"
   - You should see your images getting added to the catalog
9. What you do next is up to you...