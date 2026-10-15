# Administrator Authentication

RCH stores its administrator credentials in `runtime/auth.json`, alongside `runtime/rch.db`.

If `auth.json` does not exist when the server starts, RCH creates it with a random administrator password, API token, and session secret. The initial username and password are printed to the server's startup output once (including `nohup.out` when stdout is redirected there). Save the password securely and keep that log private.

Passwords are stored as salted scrypt hashes. To reset the password, stop the server, edit `auth.json`, replace the `password` value with `plain:your-new-password`, save the file, and start RCH again. RCH hashes the new password and writes it back; the API token and session secret remain unchanged. Restarting normally does not print a password.

Deleting `auth.json` resets all three credentials on the next start. Existing sessions and external API clients using the old token will need to authenticate again. An invalid existing file prevents startup rather than silently resetting credentials. Keep `auth.json` out of version control and backups shared with others.
