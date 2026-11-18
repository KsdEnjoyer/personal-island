# Local password viewer. Never writes the password to logs or the clipboard.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference='Stop'
$file=Join-Path $env:LOCALAPPDATA 'PersonalIsland/waicore-mcp/owner.json'
$owner=Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
[Windows.Forms.Application]::EnableVisualStyles()
$form=New-Object Windows.Forms.Form
$form.Text='Personal Island · ChatGPT без API'
$form.ClientSize=New-Object Drawing.Size(640,310)
$form.StartPosition='CenterScreen'; $form.MaximizeBox=$false; $form.FormBorderStyle='FixedDialog'
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$label=New-Object Windows.Forms.Label
$label.Text='В ChatGPT добавь свой MCP-сервер с авторизацией OAuth.'
$label.SetBounds(20,20,600,30); $form.Controls.Add($label)
$url=New-Object Windows.Forms.TextBox
$url.Text=$owner.public_base+'/mcp'; $url.ReadOnly=$true; $url.SetBounds(20,58,600,28); $form.Controls.Add($url)
$label2=New-Object Windows.Forms.Label
$label2.Text='Пароль вводи на странице Personal Island при подключении.'
$label2.SetBounds(20,110,600,30); $form.Controls.Add($label2)
$password=New-Object Windows.Forms.TextBox
$password.Text=$owner.owner_password; $password.ReadOnly=$true; $password.UseSystemPasswordChar=$true
$password.SetBounds(20,147,600,28); $form.Controls.Add($password)
$show=New-Object Windows.Forms.CheckBox
$show.Text='Показать пароль'; $show.SetBounds(20,185,280,28)
$show.Add_CheckedChanged({$password.UseSystemPasswordChar=!$show.Checked}); $form.Controls.Add($show)
$open=New-Object Windows.Forms.Button
$open.Text='Открыть плагины ChatGPT'; $open.SetBounds(20,235,300,36)
$open.Add_Click({Start-Process 'https://chatgpt.com/plugins'}); $form.Controls.Add($open)
$form.Add_FormClosed({$password.Clear();$owner=$null})
$null=$form.ShowDialog(); $form.Dispose()
