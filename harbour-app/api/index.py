"""Vercel serverless entry point for Harbour."""

from app import app

# Vercel recognizes ASGI applications exported as ``app``. ``handler`` keeps
# compatibility with older versions of the Python runtime as well.
handler = app
