from PyQt5.QtCore import pyqtSignal, QObject
from PyQt5.QtWidgets import QApplication,\
                            QDialog, \
                            QFileDialog
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.uic import loadUi
from copier import copytree2
import os.path
import sys
import json
import sh
import threading
import time

# TODO: Handle exceptions better, with error messages!
# TODO: Try to unmount disks if possible, confirmation window needed.


class WarningBox(QDialog):
    def __init__(self, text):
        super(WarningBox, self).__init__()
        loadUi('ui/warning.ui', self)

        # Signal-slot connections
        self.agreeBtn.clicked.connect(self.close)

        self.msgText.setText(text)

        # Show window
        self.exec_()


class QuestionBox(QDialog):
    def __init__(self, windowTitle, text):
        super(QuestionBox, self).__init__()
        loadUi('ui/question.ui', self)
        self.setWindowTitle(windowTitle)

        # Signal-slot connections
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
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
            self.sudo.whoami()  # Run simple to command to check
            return True
        except Exception:
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
        # This makes sure the sudo from self.sudo "dies" and only the returning sudo will be used
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
        self.workFolders = {  # Allow user to change them?
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
        fileName, _ = QFileDialog.getOpenFileName(self, "QFileDialog.getOpenFileName()", "",
                                                  "Image Files (*.iso *.img);;All Files (*)",
                                                  options=options)
        if fileName:
            self.imgLocation.setText(fileName)

    def listAvailableDevices(self):
        devices = sh.lsblk('-pJS', '-o', 'name,tran,model,size')
        devices = json.loads(str(devices))
        usb_devices = []
        for device in devices["blockdevices"]:
            if 'usb' in device['tran']:
                usb_devices.append(device)

        return usb_devices  # List of USB devices

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

        elif str(sh.whoami()) != "root":
            sudo = GetSudo()
            self.sudo = sudo.getSudo()
            if not self.sudo:
                self.qtSignals.setLabel.emit("Unable to proceed without permission!")
                return False

        # Starts process
        unmount, mounted_points = self.checkIfAnyMounted()

        if unmount is True and bool(mounted_points) is True:
            for mounted_point in mounted_points:
                self.sudo.umount(mounted_point)
        elif unmount is False and bool(mounted_points) is True:
            WarningBox("Unable to continue without unmounting USB device.")
            return 1

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
        copytree2(self.workFolders['iso'], self.workFolders['usb'],
                  informStatus=self.qtSignals.setLabel.emit)

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
        with open(self.deviceFilePath, 'wb') as usbFile, \
             open('/dev/zero', 'rb') as zeroFile:
            usbFile.write(zeroFile.read(512))

        # Formatting device
        self.qtSignals.setLabel.emit("Formatting device...")
        self.sudo.bash('-c', f"echo ',,c;' | sfdisk {self.deviceFilePath}")

        self.progressBar.valueChanged.emit(1)  # Set progress bar to 1% here (psychological effect)
        # TODO: Allow custom label
        self.sudo.bash('-c', f'mkfs.vfat -F32 {self.deviceFilePath}1 -n WINDOWS')

        # Writing to MBR
        self.qtSignals.setLabel.emit("Writing to MBR...")
        with open(self.deviceFilePath, 'wb') as usbFile, \
             open('/usr/lib/syslinux/mbr/mbr.bin', 'rb') as mbrFile:
            usbFile.write(mbrFile.read(440))

        # Installing syslinux
        self.qtSignals.setLabel.emit("Installing syslinux...")
        self.sudo.syslinux('-i', "{}1".format(self.deviceFilePath))

        # Restore device file original permissions
        self.sudo.chmod(660, self.deviceFilePath)
        self.qtSignals.setLabel.emit("Ready to copy files!")

    def checkIfAnyMounted(self):
        devices_mounted = str(sh.findmnt('-o', 'SOURCE,TARGET', '-J'))
        isos_mounted = str(self.sudo.losetup('--list', '-J', '-O', 'NAME,BACK-FILE'))
        filesystems = json.loads(devices_mounted)['filesystems']
        unmount_device = False
        usb_mounted = False

        mounted_points = []
        if filesystems:
            for filesystem in filesystems:
                for device in filesystem.get('children'):
                    if self.deviceFilePath is device.get('source') or \
                       self.deviceFilePath in device.get('source'):
                        mounted_points.append(device.get('source'))
                        usb_mounted = True

        if isos_mounted:
            isos_mounted = json.loads(isos_mounted)
            for iso in isos_mounted.get('loopdevices'):
                if self.imageFilePath is iso.get('back-file') or \
                   self.imageFilePath in iso.get('back-file'):
                    mounted_points.append(iso.get('back-file'))

        if usb_mounted:
            window_title, msg = ("Unmount USB device?",
                                 f"USB device {self.deviceFilePath} is already mounted!\n" +
                                 "Would you like to unmount it?")
            unmount_device = QuestionBox(window_title, msg).result()  # Spawns Question Dialog

        if unmount_device and usb_mounted:
            return True, mounted_points
        elif not unmount_device and usb_mounted:
            return False, mounted_points
        elif not unmount_device and not usb_mounted:
            return False, []

    def prepareEnv(self):
        # Create temporary folders
        sh.mkdir('-p', self.workFolders['usb'], self.workFolders['iso'])

        # Mount device and Image file
        self.qtSignals.setLabel.emit("Mounting device and image...")
        self.sudo.mount('-o', 'uid={}'.format(str(sh.whoami()).strip()),
                              '{}1'.format(self.deviceFilePath), self.workFolders['usb'])
        self.sudo.mount('-o', 'loop', '{}'.format(self.imageFilePath), self.workFolders['iso'])

        # Copy syslinux modules to usb drive
        self.qtSignals.setLabel.emit("Copying syslinux modules...")
        sh.cp('-r', '/usr/lib/syslinux/modules/bios/', self.workFolders['usb'])
        sh.mv(self.workFolders['usb'] + '/bios/', self.workFolders['usb'] + 'syslinux')

        # Create syslinux.cfg for Windows boot
        self.qtSignals.setLabel.emit("Writing syslinux.cfg...")
        with open(self.workFolders['usb'] + 'syslinux/syslinux.cfg', 'w') as f:
            windows_syslinux_cfg = "default boot\nLABEL boot\nMENU LABEL boot\n" + \
                                   "COM32 chain.c32\nAPPEND fs ntldr=/bootmgr"
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
                barValue = 99  # Again, for psychological effects

            self.progressBar.valueChanged.emit(barValue)
            time.sleep(0.1)  # Reduce CPU usage ; There are better ways, but for now sleep works

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
