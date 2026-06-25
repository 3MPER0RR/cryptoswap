#!/usr/bin/env python3
"""Launcher — esegui da qualsiasi directory."""
import sys
import os

# aggiunge la root del progetto al path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# lancia la CLI
from cli.swap import main
main()
