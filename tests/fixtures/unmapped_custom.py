"""
Script raising an unmapped custom 3rd-party exception.
PyThaiTrace must handle this via the Universal __FALLBACK__ engine,
extracting module, class name, docstring, and search URLs without crashing.
"""

class CloudServiceConnectionTimeout(Exception):
    """Raised when a remote cloud storage cluster fails to acknowledge handshakes within the configured TTL."""
    pass

def trigger_cloud_failure():
    raise CloudServiceConnectionTimeout("Failed to connect to cluster endpoint 'sg-region-db-01.internal' after 30000ms")

if __name__ == "__main__":
    trigger_cloud_failure()
