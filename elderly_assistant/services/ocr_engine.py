# -*- coding: utf-8 -*-
# services/ocr_engine.py
"""OCR?? - ??Tesseract??????"""
import cv2
import pytesseract
from utils.logger import setup_logger


class OCREngine:
    """OCR??????"""
    
    def __init__(self):
        self.logger = setup_logger()
        self.available = False
        self._init_error = None

    def _check_tesseract(self):
        """??Tesseract????"""
        try:
            import subprocess
            result = subprocess.run(
                ['tesseract', '--version'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                self.logger.info('Tesseract OCR ??')
                self.available = True
                return True
            else:
                self._init_error = 'Tesseract???'
                self.logger.error('Tesseract???')
                return False
        except FileNotFoundError:
            self._init_error = 'Tesseract???????: sudo apt install tesseract-ocr tesseract-ocr-chi-sim'
            self.logger.error(self._init_error)
            return False
        except Exception as e:
            self._init_error = f'Tesseract????: {e}'
            self.logger.error(self._init_error)
            return False

    def recognize_text(self, image_path):
        """????????
        
        Args:
            image_path: ??????
            
        Returns:
            ?????????
        """
        if not self.available and self._init_error is None:
            self._check_tesseract()

        if not self.available:
            self.logger.warning(f'OCR ?????: {self._init_error}')
            return ''

        try:
            # ????
            img = cv2.imread(image_path)
            if img is None:
                self.logger.error(f'??????: {image_path}')
                return ''

            # ???????
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # ??Tesseract????
            # --psm 6: ??????????
            # -l chi_sim: ????
            text = pytesseract.image_to_string(
                gray,
                lang='chi_sim',
                config='--psm 6'
            )

            return text.strip()

        except Exception as e:
            self.logger.error(f'OCR ????: {e}')
            return ''

    def get_error_message(self):
        """?????????"""
        return self._init_error
