SCRIPT_METADATA = {
    "name": "test/picker/keychain_login_picker",
    "display_name": "Keychain Login Picker Demo",
    "description": "Demonstrates filling a username and password from one Keychain Login selection.",
    "platforms": ["*"],
    "category": "Examples",
    "tags": ["keychain", "parameters", "demo"],
    "params": [
        {
            "name": "username",
            "label": "Username",
            "type": "string",
            "required": True,
            "description": "Filled together with the password by the Login picker, or entered manually.",
        },
        {
            "name": "password",
            "label": "Password",
            "type": "password",
            "required": True,
            "description": "Select a Login credential with the key icon, or enter a password manually.",
            "keychain_picker": {
                "kind": "login",
                "bindings": {
                    "username": "username",
                    "secret_value": "password",
                },
            },
        },
    ],
}

username = str(kwargs.get("username") or "")
password = str(kwargs.get("password") or "")
print("Credential type: Login")
print(f"Username provided: {'yes' if username else 'no'}")
print(f"Password provided: {'yes' if password else 'no'}")
print(f"Password length: {len(password)}")
