
import sys
import unittest
from unittest.mock import MagicMock, patch
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from pages.display_page import DisplayPage, SensorWorker

class TestDisplayPage(unittest.TestCase):
    def setUp(self):
        self.app = QApplication(sys.argv)
        self.page = DisplayPage()

    def test_page_creation(self):
        self.assertIsInstance(self.page, DisplayPage)
        self.assertEqual(self.page.timer_label.text(), "00:00:00")

    def test_start_job_timer(self):
        with patch.object(self.page.timer, 'start') as mock_start:
            self.page.start_job_timer()
            mock_start.assert_called_with(1000)
            self.assertEqual(self.page.elapsed_time.toString("hh:mm:ss"), "00:00:00")

    @patch('pages.display_page.QMessageBox')
    def test_end_print_button_shows_message_box(self, mock_qmessagebox):
        self.page.end_print_button.click()
        mock_qmessagebox.assert_called_once()
        instance = mock_qmessagebox.return_value
        instance.exec_.assert_called_once()

    def tearDown(self):
        self.page.close()

if __name__ == '__main__':
    unittest.main()
