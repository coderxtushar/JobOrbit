"""Opt-in, read-only email response tracking.

``classifier`` decides what an email is, ``extract`` reads the facts it states,
``matching`` finds the application it is about, ``service`` stores the reduced record and
proposes a change for the user to accept, and ``gmail`` is one way of feeding it messages
(a pasted ``.eml`` is the other). Nothing in this package sends mail or changes an
application without the user accepting the suggestion.
"""
