// Static one-liner entries; mode-specific bootstrap fields are rendered in OneLinersDialog.
export const terminalOneLiners = [
  {
    label: 'Python',
    code:
      'python3 -c "import requests; exec(requests.post(\'http://{{server_host}}:{{web_port}}/api/agent/bootstrap\', json={{bootstrap_payload_python}}).text)"',
  },
  {
    label: 'Windows PowerShell',
    code:
      '$ip="{{server_host}}";' +
      '$p={{web_port}};' +
      'iwr "http://$($ip):$p/api/agent/bootstrap/ps1" ' +
      '-Method Post ' +
      '-ContentType "application/json" ' +
      '-UseBasicParsing ' +
      '-Body "{{bootstrap_payload_ps1}}" ' +
      '-OutFile "$env:TEMP\\bootstrap.ps1"; ' +
      '& "$env:TEMP\\bootstrap.ps1"',
  },
]
