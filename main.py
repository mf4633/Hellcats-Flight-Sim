#!/usr/bin/env python3
"""
Hellcats Flight Simulator — Launcher
=====================================
Entry point that launches the Enhanced Edition.
"""

from game import EnhancedHellcatsSimulator

if __name__ == "__main__":
    simulator = EnhancedHellcatsSimulator()
    simulator.run()
