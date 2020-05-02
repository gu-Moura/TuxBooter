from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import QApplication,\
                            QDialog, \
                            QFileDialog, \
                            QComboBox
from PyQt5.uic import loadUi
from functools import partial
from copier import copytree2
import sys
import json
import sh
import threading
import time


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
        self.totalFilesToCopy = -1

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
        progressBar = threading.Thread(target=self.copyProgress)
        usbMaker = threading.Thread(target=self.createUSB, args=(progressBar,))
        
        progressBar.daemon = True
        usbMaker.daemon = True

        usbMaker.start()
        # usbMaker.join()

    def createUSB(self, progressBar):
        self.startBtn.setEnabled(False)
        self.prepareDrive()
        self.prepareEnv()

        progressBar.start()
        copytree2(self.workFolders['iso'], self.workFolders['usb'], informStatus=self.statusLabel.setText)

        self.statusLabel.setText('Syncing changes to disk...!')
        self.destroyEnv()

        self.startBtn.setEnabled(True)
        self.progressBar.setValue(100)
        self.statusLabel.setText('Bootable USB completed!')
        progressBar.join()

    def prepareDrive(self):
        # We need to extend the file's permissions for a moment so we can write to it!
        self.sudo.chmod(666, self.deviceFilePath)

        # Zeroing MBR
        self.statusLabel.setText("Writing zeros to MBR...")
        with open(self.deviceFilePath, 'wb') as usbFile, open('/dev/zero', 'rb') as zeroFile:
            usbFile.write(zeroFile.read(512))
        
        # Formatting device
        self.statusLabel.setText("Formatting device...")
        self.sudo.bash('-c', "echo ',,c;' | sfdisk {}".format(self.deviceFilePath))

        self.progressBar.setValue(1) # Set progress bar to 1% here for psychological effect
        self.sudo.bash('-c', 'mkfs.vfat -F32 {}1 -n {}'.format(self.deviceFilePath, 'WINDOWS')) #TODO: Allow custom label

        # Writing to MBR
        self.statusLabel.setText("Writing to MBR...")
        with open(self.deviceFilePath, 'wb') as usbFile, open('/usr/lib/syslinux/mbr/mbr.bin', 'rb') as mbrFile:
            usbFile.write(mbrFile.read(440))

        # Installing syslinux
        self.statusLabel.setText("Installing syslinux...")
        self.sudo.syslinux('-i', "{}1".format(self.deviceFilePath))

        # Restore device file original permissions
        self.sudo.chmod(660, self.deviceFilePath)
        self.statusLabel.setText("Ready to copy files!")

    def prepareEnv(self):
        # Create temporary folders
        sh.mkdir('-p', self.workFolders['usb'], self.workFolders['iso'])
        
        # Mount device and Image file
        self.statusLabel.setText("Mounting device and image...")
        self.sudo.mount('-o', 'uid={}'.format(str(sh.whoami()).strip()), '{}1'.format(self.deviceFilePath), self.workFolders['usb'])
        self.sudo.mount('-o', 'loop', '{}'.format(self.imageFilePath), self.workFolders['iso'])

        # Copy syslinux modules to usb drive
        self.statusLabel.setText("Copying syslinux modules...")
        sh.cp('-r', '/usr/lib/syslinux/modules/bios/', self.workFolders['usb'])
        sh.mv(self.workFolders['usb'] + '/bios/', self.workFolders['usb'] + 'syslinux')

        # Create syslinux.cfg for Windows boot
        self.statusLabel.setText("Writing syslinux.cfg...")
        with open(self.workFolders['usb'] + 'syslinux/syslinux.cfg', 'w') as f:
            windows_syslinux_cfg = "default boot\nLABEL boot\nMENU LABEL boot\nCOM32 chain.c32\nAPPEND fs ntldr=/bootmgr"
            f.write(windows_syslinux_cfg)
        self.statusLabel.setText("Config written!")

    def copyProgress(self):
        barValue = self.progressBar.value()

        while barValue < 99:
            if self.totalFilesToCopy == -1:
                self.totalFilesToCopy = len(list(sh.find(self.workFolders['iso'], '-type', 'f')))
            
            currentFilesCopied = len(list(sh.find(self.workFolders['usb'], '-type', 'f')))
            barValue = 100 * currentFilesCopied / self.totalFilesToCopy

            if barValue > 99:
                barValue = 99 # Again, for psychological effects
            
            self.progressBar.setValue(barValue)
            time.sleep(0.1) # Reduce CPU usage ; There are better ways, but for now sleep works fine

    def destroyEnv(self):
        self.sudo.umount(self.imageFilePath)
        self.sudo.umount(self.deviceFilePath+'1')
        self.statusLabel.setText('Cleaning up...')
        sh.rm('-rf', self.workFolders['tmp'])

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TuxBooter(str(input('Enter password for root: ')))
    
    window.show()
    sys.exit(app.exec_())