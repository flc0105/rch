from client.jobs.core.job import Job


JOB_METADATA = {
    "name": "keychain_secret_picker",
    "display_name": "Keychain Secret Picker Demo",
    "description": "Demonstrates selecting a single Secret value for a background job.",
    "platforms": ["*"],
    "category": "Examples",
    "tags": ["keychain", "parameters", "demo"],
    "execution": {
        "default": "inproc",
        "allowed": ["inproc", "subprocess"],
    },
    "params": [
        {
            "name": "password",
            "label": "Password / Secret",
            "type": "password",
            "required": True,
            "description": "Select a Secret with the key icon, or enter a value manually.",
            "keychain_picker": {
                "kind": "secret",
                "bindings": {"secret_value": "password"},
            },
        },
    ],
}


class KeychainSecretPicker(Job):
    def run(self):
        self.mark_running()
        secret = str(self.get_job_param("password") or "")
        self.send_to_server(
            1,
            "Keychain Secret received: "
            f"present={'yes' if bool(secret) else 'no'}, length={len(secret)}",
        )
        self.mark_stopped()
