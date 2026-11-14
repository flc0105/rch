"""The Configuration CLI table is a projection of the full GET Control payload.

The Client GET result stays complete for Web's editing controls. Only the
Server terminal presenter uses this read-only view.
"""


def configuration_cli_items(result):
    """The same four fields, in the same order, for text and JSON output."""
    rows = [
        {'group': item['group'], 'key': item['key'], 'value': item['value'],
         'default': item['default_value']}
        for item in result['items']
    ]
    return sorted(rows, key=lambda row: (str(row['group']).casefold(), str(row['key']).casefold()))
