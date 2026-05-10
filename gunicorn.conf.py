"""Production defaults for Lumen.

Stream cancellation and active SSE replay currently use in-process state in
routes.py, so multiple worker processes can route a cancel request to the wrong
process. Keep a single worker and use threads for concurrency until stream state
is moved to an external broker such as Redis.
"""
workers = 1
threads = 4
