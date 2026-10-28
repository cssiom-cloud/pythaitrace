"""
Fixture for ModuleNotFoundError: importing non-existent module.
"""

def load_dependencies():
    # non_existent_cloud_sdk_xyz does not exist
    import non_existent_cloud_sdk_xyz

if __name__ == "__main__":
    load_dependencies()
