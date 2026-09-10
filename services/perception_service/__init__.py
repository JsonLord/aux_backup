"""Perception: what a persona's eyes and attention make of a page.

Kept separate from the journey worker because it is the one part of a run that is
about pixels rather than about actions, and because its heavier optional
dependency -- a screen parser that turns pixels into elements without a DOM --
should not be a hard requirement of running a journey at all.
"""
from .optics import Eyes, legibility, see
from .perceive import observation_text, perceive
from .salience import motion_map, salience_of
from .scanpath import Scanner, choose_pattern, scan

__all__ = ["Eyes", "Scanner", "choose_pattern", "legibility", "motion_map", "observation_text",
           "perceive", "salience_of", "scan", "see"]
