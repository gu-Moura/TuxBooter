from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import QApplication,\
                            QDialog, \
                            QFileDialog, \
                            QComboBox
from PyQt5.uic import loadUi
from functools import partial
import sys
import shutil
import json
import sh



class TuxBooter (QDialog):
    def __init__(self, sudo_password):
        super(TuxBooter, self).__init__()
        loadUi('ui/mainWindow.ui', self)

        #TODO: Set this on press start button (ask password)
        self.sudo = sh.sudo.bake("-S", _in=sudo_password)

        # Variables
        self.deviceFilePath = ''
        self.imageFilePath = ''
        self.workFolders = { #  Allow user to change them?
            'tmp': '/tmp/tuxbooter/', 
            'usb': '/tmp/tuxbooter/usb/', 
            'iso': '/tmp/tuxbooter/iso/'
        }

        # Startup
        self.refreshUsbList()

        # Connects
        self.fileSearch.clicked.connect(self.openFileNameDialog)
        self.usbList.activated.connect(self.setUsbDevice)
        self.refreshUsb.clicked.connect(self.refreshUsbList)
        self.startBtn.clicked.connect(self.burnImage)
    
    def refreshUsbList(self):
        self.usbList.clear()
        self.usbList.addItem('<USB Devices>')
        self.deviceFilePath = ''
        for device in self.listAvailableDevices():
            self.usbList.addItem(' '.join([device["model"], device["size"]]))

    def setUsbDevice(self):
        self.deviceFilePath = ''
        for device in self.listAvailableDevices():
            if self.usbList.currentText() == ' '.join([device["model"], device["size"]]):
                self.deviceFilePath = device['name']

    def openFileNameDialog(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", "","Image Files (*.iso *.img);;All Files (*)", options=options)
        if fileName:
            self.imgLocation.setText(fileName)
            self.imageFilePath = fileName
        
    def listAvailableDevices(self):
        devices = sh.lsblk('-pJS', '-o', 'name,tran,model,size')
        devices = json.loads(str(devices))
        usb_devices = []
        for device in devices["blockdevices"]:
            if 'usb' in device['tran']:
                usb_devices.append(device)
        
        return usb_devices # List of USB devices

    def burnImage(self):
        print(self.deviceFilePath)
        print(self.imageFilePath)
        self.prepareDrive()
        self.prepareEnv()
        self.copyFiles()
        self.destroyEnv()
        print('Bootable USB completed!')

    def prepareDrive(self):
        # We need to extend the file's permissions for a moment so we can write to it!
        self.sudo.chmod(666, self.deviceFilePath)

        # Zeroing MBR
        with open(self.deviceFilePath, 'wb') as usbFile, open('/dev/zero', 'rb') as zeroFile:
            usbFile.write(zeroFile.read(512))
            print('Zeroed')
        
        # Reformatting drive
        self.sudo.bash('-c', "echo ',,c;' | sfdisk {}".format(self.deviceFilePath))
        self.sudo.bash('-c', 'mkfs.vfat -F32 {}1 -n {}'.format(self.deviceFilePath, 'WINDOWS')) #TODO: Allow custom label
        print('Formatted')

        # Writing to MBR
        with open(self.deviceFilePath, 'wb') as usbFile, open('/usr/lib/syslinux/mbr/mbr.bin', 'rb') as mbrFile:
            usbFile.write(mbrFile.read(440))
            print('MBR written')

        # Installing syslinux
        self.sudo.syslinux('-i', "{}1".format(self.deviceFilePath))
        print('Syslinux installed')

        # Restore device file original permissions
        self.sudo.chmod(660, self.deviceFilePath)

    def prepareEnv(self):
        # Create temporary folders
        sh.mkdir('-p', self.workFolders['usb'], self.workFolders['iso'])
        print("Directories created!")
        
        # Mount device and Image file
        self.sudo.mount('-o', 'uid={}'.format(str(sh.whoami()).strip()), '{}1'.format(self.deviceFilePath), self.workFolders['usb'])
        self.sudo.mount('-o', 'loop', '{}'.format(self.imageFilePath), self.workFolders['iso'])
        print("Drive and Image mounted")

        # Copy syslinux modules to usb drive
        sh.cp('-r', '/usr/lib/syslinux/modules/bios/', self.workFolders['usb'])
        sh.mv(self.workFolders['usb'] + '/bios/', self.workFolders['usb'] + 'syslinux')
        print("Modules copied!")

        # Create syslinux.cfg for Windows boot
        with open(self.workFolders['usb'] + 'syslinux/syslinux.cfg', 'w') as f:
            windows_syslinux_cfg = "default boot\nLABEL boot\nMENU LABEL boot\nCOM32 chain.c32\nAPPEND fs ntldr=/bootmgr"
            f.write(windows_syslinux_cfg)
        print("Config written!")
        
    def copyFiles(self):
        # Add progress bar
        pass
    
    def destroyEnv(self):
        # Cleanup
        self.sudo.umount(self.deviceFilePath+'1')
        self.sudo.umount(self.imageFilePath)
        print('Device and Image unmounted!')

        sh.rm('-rf', self.workFolders['tmp'])
        print("folder {} removed!".format(self.workFolders['tmp']))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TuxBooter(str(input('Enter password for root: ')))
    
    window.show()
    sys.exit(app.exec_())