from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import QApplication,\
                            QDialog, \
                            QFileDialog, \
                            QComboBox
from PyQt5.uic import loadUi
from functools import partial
import sys
import os
import shutil
import json

DEBUG = True



class TuxBooter (QDialog):
    def __init__(self):
        super(TuxBooter, self).__init__()
        loadUi('ui/mainWindow.ui', self)

        # Variables
        self.deviceFilePath = ''
        self.imageFilePath = ''

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
        bashCommand = "lsblk -pJS -o name,tran,model,size"
        devices = os.popen(bashCommand).read()
        devices = json.loads(devices)
        usb_devices = []
        for device in devices["blockdevices"]:
            if 'usb' in device['tran']:
                usb_devices.append(device)
        
        return usb_devices # List of USB devices

    def burnImage(self):
        print(self.deviceFilePath)
        print(self.imageFilePath)
        self.prepareDrive()
        

    def prepareDrive(self):
        # Zeroing MBR
        with open(self.deviceFilePath, 'wb') as usbFile, open('/dev/zero', 'rb') as zeroFile:
            usbFile.write(zeroFile.read(512))
            print('Zeroed')
        
        # Reformatting drive
        os.system("echo ',,7;*' | sfdisk {} >/dev/null 2>&1".format(self.deviceFilePath))
        os.system('mkfs.vfat -F32 {}1 -n {} >/dev/null 2>&1'.format(self.deviceFilePath, 'WINDOWS')) #TODO: Allow custom label
        print('Formatted')

        # Writing to MBR
        with open(self.deviceFilePath, 'wb') as usbFile, open('/usr/lib/syslinux/mbr/mbr.bin', 'rb') as mbrFile:
            usbFile.write(mbrFile.read(440))
            print('MBR written')

        # Installing syslinux
        os.system("syslinux -i {}1 >/dev/null 2>&1".format(self.deviceFilePath))
        print('Syslinux installed')


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TuxBooter()
    
    window.show()
    sys.exit(app.exec_())