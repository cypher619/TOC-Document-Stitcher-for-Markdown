# main.py
import sys
from PyQt6.QtWidgets import QApplication
from gui import StitcherGUI

def main():
    app = QApplication(sys.argv)
    window = StitcherGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
