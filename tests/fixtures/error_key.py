"""
Fixture for KeyError: accessing missing dict key.
"""

def lookup_user():
    user_record = {
        "id": 1001,
        "username": "sombat_developer"
    }
    # "email" is not present in dictionary
    user_email = user_record["email"]
    return user_email

if __name__ == "__main__":
    lookup_user()
