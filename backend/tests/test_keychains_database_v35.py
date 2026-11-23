"""Keychains persist encrypted, without relying on the previous JSON store."""
import sqlite3

import pytest

from server.application.keychains.keychain_store import KeychainStore
from server.persistence.rch_database import RchDatabase


def new_store(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    return db, KeychainStore(db, key_file_path=tmp_path / 'keychains.key')


def test_keychains_encrypted_roundtrip_reopen_and_machine_scopes(tmp_path):
    db, store = new_store(tmp_path)
    login = store.create_item({
        'machine_id': 'mac-one', 'hostname': 'Mac', 'kind': 'login',
        'name': 'SSH', 'username': 'alice', 'secret_value': '中文🐈pass',
        'site': 'https://example.invalid', 'note': 'lab',
    })
    secret = store.create_item({
        'machine_id': '__shared__', 'kind': 'secret', 'name': 'API',
        'secret_value': 'the bearer token', 'note': 'shared',
    })
    assert store.list_items('mac-one')[0]['has_secret'] is True
    assert 'secret_value' not in store.list_items('mac-one')[0]
    assert store.get_item(login['cred_id'])['secret_value'] == '中文🐈pass'
    assert store.get_item_by_name('mac-one', 'ssh', 'login')['username'] == 'alice'
    assert store.get_item_by_name('__shared__', 'api', 'secret')['secret_value'] == 'the bearer token'
    assert len(store.list_stored_machines()) == 2
    assert {entry['machine_id'] for entry in store.list_stored_machines()} == {'mac-one', '__shared__'}

    with sqlite3.connect(tmp_path / 'rch.db') as conn:
        rows = conn.execute('SELECT secret_ciphertext FROM keychain_entries').fetchall()
        assert len(rows) == 2
        assert all('pass' not in row[0] and 'bearer token' not in row[0] for row in rows)
        assert all(len(row[0]) > 64 for row in rows)
    assert b'pass' not in (tmp_path / 'rch.db').read_bytes()
    assert b'bearer token' not in (tmp_path / 'rch.db').read_bytes()
    assert (tmp_path / 'keychains.key').is_file()
    reopened = KeychainStore(db, key_file_path=tmp_path / 'keychains.key')
    assert reopened.get_item(login['cred_id'])['secret_value'] == '中文🐈pass'
    assert reopened.get_item(secret['cred_id'])['secret_value'] == 'the bearer token'
    assert len(reopened.list_items()) == 2


def test_keychains_update_scope_move_delete_and_duplicate_rollback(tmp_path):
    db, store = new_store(tmp_path)
    first = store.create_item({'machine_id': 'one', 'kind': 'login', 'name': 'ssh', 'username': 'one', 'secret_value': 'abc'})
    second = store.create_item({'machine_id': 'two', 'kind': 'secret', 'name': 'ssh', 'secret_value': 'def'})
    with pytest.raises(ValueError, match='already exists'):
        store.create_item({'machine_id': 'one', 'kind': 'secret', 'name': 'SSH', 'secret_value': 'third'})
    with pytest.raises(ValueError, match='already exists'):
        store.update_item(first['cred_id'], {'machine_id': 'two'})
    assert store.get_item(first['cred_id'])['machine_id'] == 'one'
    updated = store.update_item(first['cred_id'], {'machine_id': '__shared__', 'name': 'ssh-main', 'note': 'moved'})
    assert updated['cred_id'] == first['cred_id']
    assert updated['secret_value'] == 'abc'
    assert store.get_item(first['cred_id'])['machine_id'] == '__shared__'
    assert store.get_item_by_name('__shared__', 'ssh-main')['secret_value'] == 'abc'
    with pytest.raises(FileNotFoundError):
        store.get_item_by_name('one', 'ssh')
    store.update_item(second['cred_id'], {'secret_value': 'changed'})
    assert store.get_item(second['cred_id'])['secret_value'] == 'changed'
    deleted = store.delete_item(second['cred_id'])
    assert deleted['secret_value'] == 'changed'
    with pytest.raises(FileNotFoundError):
        store.get_item(second['cred_id'])
    assert store.public_item(deleted)['has_secret'] is True


def test_missing_key_is_fail_closed(tmp_path):
    db, store = new_store(tmp_path)
    assert store.list_items() == []
    item = store.create_item({'kind': 'secret', 'name': 'new', 'secret_value': 'safe'})
    (tmp_path / 'keychains.key').rename(tmp_path / 'keychains.key.backup')
    with pytest.raises(RuntimeError, match='restore'):
        KeychainStore(db, key_file_path=tmp_path / 'keychains.key')
    (tmp_path / 'keychains.key.backup').rename(tmp_path / 'keychains.key')
    assert KeychainStore(db, key_file_path=tmp_path / 'keychains.key').get_item(item['cred_id'])['secret_value'] == 'safe'


def test_empty_invalid_and_missing_entries(tmp_path):
    _, store = new_store(tmp_path)
    with pytest.raises(ValueError, match='Invalid credential'):
        store.create_item({'kind': 'login', 'name': 'x', 'secret_value': 'p'})
    with pytest.raises(ValueError, match='secret value'):
        store.create_item({'kind': 'secret', 'name': 'x', 'secret_value': ''})
    with pytest.raises(FileNotFoundError):
        store.delete_item('missing')
    assert not (tmp_path / 'keychains.key').exists()


def test_keychains_uses_existing_database_without_changing_rch_schema(tmp_path):
    db = RchDatabase(str(tmp_path / 'rch.db'))
    store = KeychainStore(db, key_file_path=tmp_path / 'keychains.key')
    store.create_item({'kind': 'secret', 'name': 'a', 'secret_value': 'b'})
    db.close_thread_connection()
    reopened_db = RchDatabase(str(tmp_path / 'rch.db'))
    assert KeychainStore(reopened_db, key_file_path=tmp_path / 'keychains.key').get_item_by_name('__shared__', 'a')['secret_value'] == 'b'


def test_web_api_preserves_list_mask_and_detail_reveal(tmp_path):
    from types import SimpleNamespace
    from server.application.web.keychain_api import WebKeychainApi

    db, store = new_store(tmp_path)
    service = SimpleNamespace(get_connections_payload=lambda: [])
    api = WebKeychainApi(server=None, keychain_store=store, connection_service=service)
    created = api.create_keychain_item({'machine_id': 'mac', 'hostname': 'Mac', 'kind': 'login',
                                        'name': 'web', 'username': 'user', 'secret_value': 'readable'})
    assert created['item']['has_secret'] is True
    assert 'secret_value' not in created['item']
    assert 'secret_value' not in api.list_keychains('mac')['items'][0]
    assert api.get_keychain_item(created['item']['cred_id'])['item']['secret_value'] == 'readable'
    assert api.resolve_keychain_item({'machine_id': 'mac', 'scope': 'machine', 'name': 'web'})['item']['secret_value'] == 'readable'
    api.update_keychain_item(created['item']['cred_id'], {'secret_value': 'new-secret'})
    assert api.get_keychain_item(created['item']['cred_id'])['item']['secret_value'] == 'new-secret'
    api.delete_keychain_item(created['item']['cred_id'])
    assert api.list_keychains('mac')['items'] == []


def test_keychains_stdlib_protection_randomizes_and_detects_changes(tmp_path):
    db, store = new_store(tmp_path)
    original = 'A' * (70 * 1024) + '\u96ea\U0001f431'
    first = store.create_item({'kind': 'secret', 'name': 'first', 'secret_value': original})
    second = store.create_item({'kind': 'secret', 'name': 'second', 'secret_value': original})
    assert store.get_item(first['cred_id'])['secret_value'] == original
    with db.transaction() as conn:
        entries = conn.execute('SELECT cred_id, secret_ciphertext FROM keychain_entries').fetchall()
        assert entries[0]['secret_ciphertext'] != entries[1]['secret_ciphertext']
        original_token = entries[0]['secret_ciphertext']
        # Keep a syntactically valid URL-safe payload with a modified authenticator.
        tampered = ('A' if original_token[0] != 'A' else 'B') + original_token[1:]
        conn.execute('UPDATE keychain_entries SET secret_ciphertext = ? WHERE cred_id = ?',
                     (tampered, first['cred_id']))
    with pytest.raises(RuntimeError, match='cannot be decrypted'):
        store.get_item(first['cred_id'])
    with db.transaction() as conn:
        conn.execute('UPDATE keychain_entries SET secret_ciphertext = ? WHERE cred_id = ?',
                     (original_token, first['cred_id']))
    assert store.get_item(first['cred_id'])['secret_value'] == original

    # A wrong key must not make unreadable secrets appear readable.
    import base64
    import secrets
    other_key = tmp_path / 'wrong.key'
    other_key.write_bytes(base64.urlsafe_b64encode(secrets.token_bytes(32)))
    wrong_store = KeychainStore(db, key_file_path=other_key)
    with pytest.raises(RuntimeError, match='cannot be decrypted'):
        wrong_store.get_item(second['cred_id'])



def test_malformed_ciphertext_is_rejected(tmp_path):
    db, store = new_store(tmp_path)
    entry = store.create_item({'kind': 'secret', 'name': 'broken', 'secret_value': 'ok'})
    for malformed in ('not-base64!', 'YWJj', ''):
        with db.transaction() as conn:
            conn.execute('UPDATE keychain_entries SET secret_ciphertext = ? WHERE cred_id = ?',
                         (malformed, entry['cred_id']))
        with pytest.raises(RuntimeError, match='cannot be decrypted'):
            store.get_item(entry['cred_id'])
