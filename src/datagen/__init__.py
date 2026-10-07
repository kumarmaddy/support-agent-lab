"""Synthetic data generator for the support resolution agent (see docs/design/data-design.md).

Layers, from the bottom up: domain (rules and vocabulary), store (database), generation (building
blocks that create data), scenarios (ticket families), then tickets and cli (assembly and entry point).
A layer may import only from layers below it.
"""
