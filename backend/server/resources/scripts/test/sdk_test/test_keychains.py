SCRIPT_METADATA = {
    "display_name": "Keychains Test",
    "description": "",
    "params": [],
    "api_grants": [
        "keychains:create",
        "keychains:resolve"
    ]
}

import time

from client.runtime.keychains import create_secret, create_login, get_secret, get_login


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    print('=== Script SDK Keychains Test ===')

    stamp = str(int(time.time() * 1000))

    machine_secret_name = f'sdk_machine_secret_{stamp}'
    machine_secret_value = f'machine-secret-value-{stamp}'

    machine_login_name = f'sdk_machine_login_{stamp}'
    machine_login_username = f'machine-user-{stamp}'
    machine_login_password = f'machine-password-{stamp}'

    server_secret_name = f'sdk_server_secret_{stamp}'
    server_secret_value = f'server-secret-value-{stamp}'

    server_login_name = f'sdk_server_login_{stamp}'
    server_login_username = f'server-user-{stamp}'
    server_login_password = f'server-password-{stamp}'

    print('--- create machine secret ---')
    created_machine_secret = create_secret(
        machine_secret_name,
        machine_secret_value,
    )
    print('created_machine_secret =', created_machine_secret)

    print('--- create machine login ---')
    created_machine_login = create_login(
        machine_login_name,
        machine_login_username,
        machine_login_password,
    )
    print('created_machine_login =', created_machine_login)

    print('--- create server secret ---')
    created_server_secret = create_secret(
        server_secret_name,
        server_secret_value,
        scope='server',
    )
    print('created_server_secret =', created_server_secret)

    print('--- create server login ---')
    created_server_login = create_login(
        server_login_name,
        server_login_username,
        server_login_password,
        scope='server',
    )
    print('created_server_login =', created_server_login)

    print('--- resolve machine secret ---')
    resolved_machine_secret = get_secret(machine_secret_name)
    resolved_machine_secret_value = resolved_machine_secret.getvalue()
    print('resolved_machine_secret =', resolved_machine_secret)
    print('resolved_machine_secret_value =', resolved_machine_secret_value)
    assert_true(
        resolved_machine_secret_value == machine_secret_value,
        'machine secret value mismatch',
    )

    print('--- resolve machine login ---')
    resolved_machine_login = get_login(machine_login_name)
    resolved_machine_username = resolved_machine_login.username
    resolved_machine_password = resolved_machine_login.password.getvalue()
    print('resolved_machine_login =', resolved_machine_login)
    print('resolved_machine_username =', resolved_machine_username)
    print('resolved_machine_password =', resolved_machine_password)
    assert_true(
        resolved_machine_username == machine_login_username,
        'machine login username mismatch',
    )
    assert_true(
        resolved_machine_password == machine_login_password,
        'machine login password mismatch',
    )

    print('--- resolve server secret ---')
    resolved_server_secret = get_secret(server_secret_name, scope='server')
    resolved_server_secret_value = resolved_server_secret.getvalue()
    print('resolved_server_secret =', resolved_server_secret)
    print('resolved_server_secret_value =', resolved_server_secret_value)
    assert_true(
        resolved_server_secret_value == server_secret_value,
        'server secret value mismatch',
    )

    print('--- resolve server login ---')
    resolved_server_login = get_login(server_login_name, scope='server')
    resolved_server_username = resolved_server_login.username
    resolved_server_password = resolved_server_login.password.getvalue()
    print('resolved_server_login =', resolved_server_login)
    print('resolved_server_username =', resolved_server_username)
    print('resolved_server_password =', resolved_server_password)
    assert_true(
        resolved_server_username == server_login_username,
        'server login username mismatch',
    )
    assert_true(
        resolved_server_password == server_login_password,
        'server login password mismatch',
    )

    print('PASS')


if __name__ == '__main__':
    main()