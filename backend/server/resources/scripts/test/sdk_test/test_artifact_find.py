SCRIPT_METADATA = {
    "display_name": "Artifact Find Test",
    "params": [],
    "api_grants": [
        "artifacts:list"
    ]
}

from client.runtime.sdk import artifact

items_server = artifact.find_by_file_name('txt', type='server_files', exact=False)


items_all = artifact.find_by_file_name('screenshot', exact=False)


print(items_server)
print(items_all)