"""Cerberus: a back-office pipeline that triages Iraqi-dialect support tickets.

The AI prepares; a human approves. Nothing in this package sends a message to a
customer: the only code that writes to the outbox is AdminQueue.approve() in
cerberus/queue.py, and it needs a named human actor.
"""

__version__ = "0.1.0"
