// Terminal toolbar one-liners are intentionally kept as static data.
// Add or remove entries here without touching toolbar/dialog rendering code.
// Supported placeholders: {{server_host}}, {{server_port}}, {{web_port}}

export const terminalOneLiners = [
  {
    label: 'Python',
    code:
      'python3 -c "import requests; exec(requests.post(\'http://{{server_host}}:{{web_port}}/api/agent/bootstrap\', json={\'server_host\':\'{{server_host}}\',\'server_port\':{{server_port}},\'web_port\':{{web_port}}}).text)"',
  },
  {
    label: 'Windows PowerShell',
    code:
      '$ip="{{server_host}}";' +
      '$sp={{server_port}};' +
      '$p={{web_port}};' +
      'iwr "http://$($ip):$p/api/agent/bootstrap/ps1" ' +
      '-Method Post ' +
      '-ContentType "application/json" ' +
      '-UseBasicParsing ' +
      '-Body "{`"server_host`":`"$ip`",`"server_port`":$sp,`"web_port`":$p}" ' +
      '-OutFile "$env:TEMP\\bootstrap.ps1"; ' +
      '& "$env:TEMP\\bootstrap.ps1"',
  },
]
