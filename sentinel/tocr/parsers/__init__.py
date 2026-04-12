#!/usr/bin/env python3
"""TOCR document parsers."""

from sentinel.tocr.parsers.atoms_parser import ATOMSParser
from sentinel.tocr.parsers.docx_parser import DOCXParser
from sentinel.tocr.parsers.essca_parser import ESSCAParser
from sentinel.tocr.parsers.pdf_parser import PDFParser

__all__ = ["ATOMSParser", "DOCXParser", "ESSCAParser", "PDFParser"]
