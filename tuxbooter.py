from PyQt5.QtCore import QDateTime, pyqtSignal, QObject
from PyQt5.QtWidgets import QApplication,\
                            QDialog, \
                            QFileDialog, \
                            QComboBox
                            
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.uic import loadUi
from functools import partial
from copier import copytree2
import os.path
import sys
import json
import sh
import threading
import time

#TODO: Handle exceptions better, with error messages! Try to unmount disks if possible, confirmation window needed

class WarningBox(QDialog):
    def __init__(self, text):
        super(WarningBox, self).__init__()
        loadUi('ui/warning.ui', self)
        
        # Signal-slot connections
        self.agreeBtn.clicked.connect(self.close)
        
        self.msgText.setText(text)

        # Show window
        self.exec_()


class GetSudo(QDialog):
    def __init__(self):
        super(GetSudo, self).__init__()
        loadUi('ui/guisudo.ui', self)

        # Variables
        self.showingPasswd = False
        self.sudo = False

        # Signal-slot connections
        self.eyeButton.clicked.connect(self.showPass)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.exec_()

    def checkPass(self):
        try:
            whoami = self.sudo.whoami() # Run simple to command to check
            return True
        except Exception as e:
            del(self.sudo)
            self.sudo = False
            return False

    def showPass(self):
        if not self.showingPasswd:
            self.passwdEdit.setEchoMode(self.passwdEdit.Normal)
            self.showingPasswd = True
            self.eyeButton.setIcon(QIcon(QPixmap("ui/assets/EyeSlashed.png")))
            # Set eye icon
        else:
            self.passwdEdit.setEchoMode(self.passwdEdit.Password)
            self.showingPasswd = False
            self.eyeButton.setIcon(QIcon(QPixmap("ui/assets/EyeOpen.png")))
            # Set slashed eye icon

    def accept(self):
        self.sudo = sh.sudo.bake("-S", _in=str(self.passwdEdit.text()))
        # verify pass
        if self.checkPass():
            QDialog.accept(self)
        else:
            WarningBox("Incorrect password!\n\nPlease try again...")

    def reject(self):
        self.sudo = False
        QDialog.reject(self)

    def getSudo(self):
        # This makes sure the sudo inside self.sudo "dies" and only the returning sudo will be used after
        sudo = self.sudo
        del(self.sudo)
        return sudo


class Signals(QObject):
    processComplete = pyqtSignal(object)
    setLabel = pyqtSignal(object)

class TuxBooter (QDialog):
    def __init__(self):
        super(TuxBooter, self).__init__()
        loadUi('ui/mainWindow.ui', self)

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
        self.qtSignals = Signals()

        # Signal-slot connections
        self.fileSearch.clicked.connect(self.openFileNameDialog)
        self.usbList.activated.connect(self.setUsbDevice)
        self.refreshUsb.clicked.connect(self.refreshUsbList)
        self.startBtn.clicked.connect(self.burnImage)
        self.progressBar.valueChanged.connect(self.progressBar.setValue)
        self.qtSignals.setLabel.connect(self.statusLabel.setText)
        self.qtSignals.processComplete.connect(self.startBtn.setEnabled)
    
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
            
        
    def listAvailableDevices(self):
        devices = sh.lsblk('-pJS', '-o', 'name,tran,model,size')
        devices = json.loads(str(devices))
        usb_devices = []
        for device in devices["blockdevices"]:
            if 'usb' in device['tran']:
                usb_devices.append(device)
        
        return usb_devices # List of USB devices

    def burnImage(self):
        # Get image file
        self.imageFilePath = self.imgLocation.text()
        
        # Verifications
        if self.deviceFilePath == '':
            WarningBox("You must select a USB device first!")
            return False

        elif not os.path.exists(self.imageFilePath) or not os.path.isfile(self.imageFilePath):
            WarningBox("You must select a valid disk image file!")
            return False
        
        elif str(sh.whoami()) is not "root":
            sudo = GetSudo()
            self.sudo = sudo.getSudo()
            if not self.sudo:
                self.qtSignals.setLabel.emit("Unable to proceed without permission!")
                return False

        

        # Starts process
        self.startBtn.setEnabled(False)

        progressBar = threading.Thread(target=self.copyProgress)
        usbMaker = threading.Thread(target=self.createUSB, args=(progressBar,))
        
        progressBar.daemon = True
        usbMaker.daemon = True

        usbMaker.start()

    def createUSB(self, progressBar):
       
        self.prepareDrive()
        self.prepareEnv()

        progressBar.start()
        copytree2(self.workFolders['iso'], self.workFolders['usb'], informStatus=self.qtSignals.setLabel.emit)

        self.qtSignals.setLabel.emit('Syncing changes to disk...!')
        self.destroyEnv()

        
        self.progressBar.valueChanged.emit(100)
        self.qtSignals.setLabel.emit('Bootable USB completed!')
        progressBar.join()

    def prepareDrive(self):
        # We need to extend the file's permissions for a moment so we can write to it!
        self.sudo.chmod(666, self.deviceFilePath)

        # Zeroing MBR
        self.qtSignals.setLabel.emit("Writing zeros to MBR...")
        with open(self.deviceFilePath, 'wb') as usbFile, open('/dev/zero', 'rb') as zeroFile:
            usbFile.write(zeroFile.read(512))
        
        # Formatting device
        self.qtSignals.setLabel.emit("Formatting device...")
        self.sudo.bash('-c', "echo ',,c;' | sfdisk {}".format(self.deviceFilePath))

        self.progressBar.valueChanged.emit(1) # Set progress bar to 1% here for psychological effect
        self.sudo.bash('-c', 'mkfs.vfat -F32 {}1 -n {}'.format(self.deviceFilePath, 'WINDOWS')) #TODO: Allow custom label

        # Writing to MBR
        self.qtSignals.setLabel.emit("Writing to MBR...")
        with open(self.deviceFilePath, 'wb') as usbFile, open('/usr/lib/syslinux/mbr/mbr.bin', 'rb') as mbrFile:
            usbFile.write(mbrFile.read(440))

        # Installing syslinux
        self.qtSignals.setLabel.emit("Installing syslinux...")
        self.sudo.syslinux('-i', "{}1".format(self.deviceFilePath))

        # Restore device file original permissions
        self.sudo.chmod(660, self.deviceFilePath)
        self.qtSignals.setLabel.emit("Ready to copy files!")

    def prepareEnv(self):
        # Create temporary folders
        sh.mkdir('-p', self.workFolders['usb'], self.workFolders['iso'])
        
        # Mount device and Image file
        self.qtSignals.setLabel.emit("Mounting device and image...")
        self.sudo.mount('-o', 'uid={}'.format(str(sh.whoami()).strip()), '{}1'.format(self.deviceFilePath), self.workFolders['usb'])
        self.sudo.mount('-o', 'loop', '{}'.format(self.imageFilePath), self.workFolders['iso'])

        # Copy syslinux modules to usb drive
        self.qtSignals.setLabel.emit("Copying syslinux modules...")
        sh.cp('-r', '/usr/lib/syslinux/modules/bios/', self.workFolders['usb'])
        sh.mv(self.workFolders['usb'] + '/bios/', self.workFolders['usb'] + 'syslinux')

        # Create syslinux.cfg for Windows boot
        self.qtSignals.setLabel.emit("Writing syslinux.cfg...")
        with open(self.workFolders['usb'] + 'syslinux/syslinux.cfg', 'w') as f:
            windows_syslinux_cfg = "default boot\nLABEL boot\nMENU LABEL boot\nCOM32 chain.c32\nAPPEND fs ntldr=/bootmgr"
            f.write(windows_syslinux_cfg)
        self.qtSignals.setLabel.emit("Config written!")

    def copyProgress(self):
        barValue = self.progressBar.value()

        while barValue < 99:
            if self.totalFilesToCopy == -1:
                self.totalFilesToCopy = len(list(sh.find(self.workFolders['iso'], '-type', 'f')))
            
            currentFilesCopied = len(list(sh.find(self.workFolders['usb'], '-type', 'f')))
            barValue = 100 * currentFilesCopied / self.totalFilesToCopy

            if barValue > 99:
                barValue = 99 # Again, for psychological effects
            
            self.progressBar.valueChanged.emit(barValue)
            time.sleep(0.1) # Reduce CPU usage ; There are better ways, but for now sleep works fine

    def destroyEnv(self):
        self.sudo.umount(self.imageFilePath)
        self.sudo.umount(self.deviceFilePath+'1')
        self.qtSignals.setLabel.emit('Cleaning up...')
        sh.rm('-rf', self.workFolders['tmp'])
        self.qtSignals.processComplete.emit(True)




if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TuxBooter()
    
    window.show()
    sys.exit(app.exec_())