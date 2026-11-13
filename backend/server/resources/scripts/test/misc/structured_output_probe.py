SCRIPT_METADATA = {
    'name': 'test/misc/structured_output_probe',
    'display_name': 'Structured Output Probe',
    'description': 'Test ordered text and structured output from the Script SDK.',
    'platforms': ['*'],
    'execution': {
        'modes': {'allowed': ['inproc', 'subprocess_pipe'], 'default': 'inproc'},
        'output': {'allowed': ['collect', 'stream'], 'default': 'stream'},
    },
    'params': [],
}

from client.runtime.sdk import context

print('Gathering Client information...', flush=True)
context.emit({
    'machine_id': context.machine_id(),
    'hostname': context.hostname(),
    'os_alias': context.os_alias(),
    'script_name': context.script_name(),
})
print('Client information emitted.', flush=True)
