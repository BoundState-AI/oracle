#!/usr/bin/env python3
"""
Module: TOCR Parsers
Purpose: TOCR document parsers.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Safety Critical: False
"""

from sentinel.tocr.parsers.atoms_parser import ATOMSParser
from sentinel.tocr.parsers.docx_parser import DOCXParser
from sentinel.tocr.parsers.essca_parser import ESSCAParser
from sentinel.tocr.parsers.pdf_parser import PDFParser

__all__ = ["ATOMSParser", "DOCXParser", "ESSCAParser", "PDFParser"]
